import asyncio
import logging
import os
import re
import sqlite3
import time
from typing import List, Dict, Optional, Tuple

from telegram import Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    AIORateLimiter,
    MessageHandler,
    CommandHandler,
    ContextTypes,
    filters,
)

import config
from gpt_engine import build_engine_from_config
from persona_manager import extract_persona_and_clean_text, build_system_prompt

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)


class ConversationStore:
    """SQLite-backed storage for per-user persona and chat history."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self) -> None:
        cur = self._conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL;")
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS user_persona (
                user_id INTEGER PRIMARY KEY,
                persona_name TEXT,
                persona_system TEXT,
                updated_ts INTEGER
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_memory (
                user_id INTEGER,
                role TEXT CHECK(role IN ('user','assistant')),
                content TEXT,
                ts INTEGER
            );
            """
        )
        self._conn.commit()

    def set_user_persona(self, user_id: int, persona_name: str, persona_system: str) -> None:
        ts = int(time.time())
        cur = self._conn.cursor()
        cur.execute(
            """
            INSERT INTO user_persona (user_id, persona_name, persona_system, updated_ts)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                persona_name=excluded.persona_name,
                persona_system=excluded.persona_system,
                updated_ts=excluded.updated_ts
            ;
            """,
            (user_id, persona_name, persona_system, ts),
        )
        self._conn.commit()

    def get_user_persona(self, user_id: int) -> Tuple[Optional[str], Optional[str]]:
        cur = self._conn.cursor()
        cur.execute("SELECT persona_name, persona_system FROM user_persona WHERE user_id=?", (user_id,))
        row = cur.fetchone()
        if row:
            return row["persona_name"], row["persona_system"]
        return None, None

    def clear_user_persona(self, user_id: int) -> None:
        cur = self._conn.cursor()
        cur.execute("DELETE FROM user_persona WHERE user_id=?", (user_id,))
        self._conn.commit()

    def append_message(self, user_id: int, role: str, content: str) -> None:
        ts = int(time.time())
        cur = self._conn.cursor()
        cur.execute(
            "INSERT INTO chat_memory (user_id, role, content, ts) VALUES (?, ?, ?, ?)",
            (user_id, role, content, ts),
        )
        # Trim to last N messages per user
        cur.execute(
            """
            DELETE FROM chat_memory
            WHERE user_id = ? AND ts NOT IN (
                SELECT ts FROM chat_memory WHERE user_id = ? ORDER BY ts DESC LIMIT ?
            )
            """,
            (user_id, user_id, config.MEMORY_MESSAGE_LIMIT * 2),  # user+assistant pairs
        )
        self._conn.commit()

    def get_recent_messages(self, user_id: int, limit: int) -> List[Dict]:
        cur = self._conn.cursor()
        cur.execute(
            "SELECT role, content FROM chat_memory WHERE user_id=? ORDER BY ts ASC",
            (user_id,),
        )
        rows = cur.fetchall()
        messages = [{"role": r["role"], "content": r["content"]} for r in rows]
        # Keep only the last `limit*2` entries for safety
        return messages[-(limit * 2) :]

    def clear_history(self, user_id: int) -> None:
        cur = self._conn.cursor()
        cur.execute("DELETE FROM chat_memory WHERE user_id=?", (user_id,))
        self._conn.commit()


class TelegramPersonaBot:
    def __init__(self) -> None:
        if not config.TELEGRAM_BOT_TOKEN or config.TELEGRAM_BOT_TOKEN == "YOUR_TELEGRAM_BOT_API_TOKEN":
            raise ValueError("TELEGRAM_BOT_TOKEN is not set. Update config.py with your token.")

        self.store = ConversationStore(config.DB_PATH)
        self.engine = build_engine_from_config()
        self.app: Application = (
            ApplicationBuilder()
            .token(config.TELEGRAM_BOT_TOKEN)
            .rate_limiter(AIORateLimiter())
            .build()
        )
        self.bot_username: Optional[str] = None
        self._openai_sem = asyncio.Semaphore(1)

        # Handlers
        self.app.add_handler(CommandHandler("start", self.on_start))
        self.app.add_handler(CommandHandler("reset", self.on_reset))
        self.app.add_handler(CommandHandler("persona", self.on_persona))
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.on_message))

    async def _ensure_bot_username(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self.bot_username:
            me = await context.bot.get_me()
            self.bot_username = me.username
            logger.info("Bot username resolved as @%s", self.bot_username)

    def _parse_strict_command(self, text: str) -> Optional[str]:
        """
        Accept only messages like: @<bot_username> "user message"
        Returns the quoted user message if pattern matches, else None.
        Supports straight and curly quotes.
        """
        if not self.bot_username:
            return None
        pattern = rf"^\s*@{re.escape(self.bot_username)}\s+([\"“”])(?P<msg>.+?)\1\s*$"
        m = re.match(pattern, text.strip(), flags=re.IGNORECASE | re.DOTALL)
        if m:
            return m.group("msg").strip()
        return None

    def _is_addressed_to_bot(self, text: str, chat_type: str) -> bool:
        # Private chats: treat all messages as addressed to the bot
        if chat_type.lower() == "private":
            return True
        aliases = {config.BOT_MENTION_ALIAS.lower()}
        if self.bot_username:
            aliases.add(f"@{self.bot_username}".lower())
        text = (text or "").strip()
        return any(text.lower().startswith(a) for a in aliases)

    def _remove_mention_prefix(self, text: str) -> str:
        if not text:
            return ""
        candidates = [config.BOT_MENTION_ALIAS]
        if self.bot_username:
            candidates.append(f"@{self.bot_username}")
        for a in candidates:
            if text.lower().startswith(a.lower()):
                return text[len(a) :].lstrip(" ,:\u200b\n\t")
        return text

    async def _safe_reply(self, update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
        chat = update.effective_chat
        if chat is None:
            return
        await context.bot.send_message(chat_id=chat.id, text=text)

    async def on_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await self._ensure_bot_username(context)
        mention = f"@{self.bot_username}" if self.bot_username else "@<your_bot_username>"
        msg = (
            "Hi! I’m your GPT-powered persona bot.\n\n"
            f"Use: {mention} \"your message here\"\n"
            "Examples:\n"
            f"- {mention} \"Hello, how are you?\"\n"
            f"- {mention} \"act like Einstein and explain relativity\"\n"
            "Commands: /persona (show/clear), /reset (clear memory)."
        )
        await self._safe_reply(update, context, msg)

    async def on_reset(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = update.effective_user
        if user is None:
            return
        self.store.clear_history(user.id)
        await self._safe_reply(update, context, "Your conversation history has been cleared.")

    async def on_persona(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = update.effective_user
        if user is None:
            return
        user_id = user.id
        if context.args and context.args[0].lower() in {"clear", "reset"}:
            self.store.clear_user_persona(user_id)
            await self._safe_reply(update, context, "Persona cleared. You can set a new one by saying 'act like ...'.")
            return
        name, _sys = self.store.get_user_persona(user_id)
        if name:
            await self._safe_reply(update, context, f"Current persona: {name}")
        else:
            await self._safe_reply(update, context, "No persona set. Say something like 'act like Einstein' to set one.")

    def _chunk_text(self, text: str, limit: int) -> List[str]:
        chunks: List[str] = []
        buf = []
        total = 0
        for line in text.splitlines(True):  # keep newlines
            if total + len(line) > limit and buf:
                chunks.append("".join(buf))
                buf, total = [], 0
            buf.append(line)
            total += len(line)
        if buf:
            chunks.append("".join(buf))
        if not chunks:
            chunks = [text[:limit]]
        return chunks

    async def on_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await self._ensure_bot_username(context)
        message = update.message
        if message is None or message.text is None:
            return

        raw_text = message.text.strip()
        # Enforce strict pattern @<username> "..."
        parsed = self._parse_strict_command(raw_text)
        if parsed is None:
            return

        user = update.effective_user
        if user is None:
            return
        user_id = user.id
        query_raw = parsed

        # Extract persona and cleaned query
        persona_name, persona_sys, cleaned_query = extract_persona_and_clean_text(query_raw)
        if persona_name and persona_sys:
            self.store.set_user_persona(user_id, persona_name, persona_sys)
            logger.info("Persona for %s set to %s", user_id, persona_name)
        else:
            persona_name, persona_sys = self.store.get_user_persona(user_id)

        if not cleaned_query:
            await self._safe_reply(update, context, "Please include a question or request in quotes.")
            return

        # Build conversation context
        history = self.store.get_recent_messages(user_id, config.MEMORY_MESSAGE_LIMIT)
        user_msg = {"role": "user", "content": cleaned_query}
        messages: List[Dict] = [*history, user_msg]

        system_prompt = build_system_prompt(config.SYSTEM_PROMPT_BASE, persona_sys)

        try:
            async with self._openai_sem:
                assistant_text = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: self.engine.generate_reply(messages=messages, system_prompt=system_prompt),
                )
        except Exception as e:
            logger.exception("OpenAI request failed: %s", e)
            await self._safe_reply(update, context, "Sorry, I had trouble generating a response. Please try again.")
            return

        # Persist messages
        self.store.append_message(user_id, "user", cleaned_query)
        self.store.append_message(user_id, "assistant", assistant_text)

        # Respect Telegram message size limits
        chat = update.effective_chat
        if chat is None:
            return
        for chunk in self._chunk_text(assistant_text, config.REPLY_MAX_CHARS):
            await context.bot.send_message(chat_id=chat.id, text=chunk)

    def run(self) -> None:
        logger.info("Starting Telegram bot...")
        self.app.run_polling()


if __name__ == "__main__":
    bot = TelegramPersonaBot()
    bot.run()