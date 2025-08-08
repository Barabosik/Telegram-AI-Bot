import logging
import threading
import time
from typing import List, Dict, Optional, Iterable, cast

import tiktoken
from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception_type
from openai import OpenAI
from openai.types.chat import ChatCompletionMessageParam

import config

logger = logging.getLogger(__name__)


def _encoding_for_model(model_name: str):
    try:
        # o200k_base is used for GPT-4o family
        return tiktoken.get_encoding("o200k_base")
    except Exception:
        try:
            return tiktoken.encoding_for_model(model_name)
        except Exception:
            # Fallback to cl100k_base
            return tiktoken.get_encoding("cl100k_base")


def _count_tokens(encoding, text: str) -> int:
    try:
        return int(len(encoding.encode(text)))
    except Exception:
        # rough fallback, ensure int
        return int(len(text.split()) * 1.3)


def _messages_token_length(encoding, messages: List[Dict]) -> int:
    total = 0
    for m in messages:
        content = m.get("content") or ""
        total += _count_tokens(encoding, content)
    return int(total)


class GPTEngine:
    """Wrapper for OpenAI chat completions with retries and trimming."""

    def __init__(
        self,
        api_key: str,
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 600,
        request_timeout_seconds: int = 40,
    ) -> None:
        if not api_key or api_key == "YOUR_OPENAI_API_KEY":
            raise ValueError("OPENAI_API_KEY is not set. Update config.py with your key.")

        self.client = OpenAI(api_key=api_key)
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.request_timeout_seconds = request_timeout_seconds
        self.encoding = _encoding_for_model(model)
        # Rate limiting state
        self._rl_lock = threading.Lock()
        self._last_call_ts = 0.0

    def _respect_min_interval(self) -> None:
        # Ensure a minimum interval between OpenAI calls
        with self._rl_lock:
            now = time.monotonic()
            elapsed = now - self._last_call_ts
            min_interval = max(0.0, float(config.OPENAI_MIN_CALL_INTERVAL_SECONDS))
            if elapsed < min_interval:
                time.sleep(min_interval - elapsed)
            self._last_call_ts = time.monotonic()

    def _trim_messages_to_fit(self, messages: List[Dict]) -> List[Dict]:
        """
        Trim the conversation to fit within a rough token budget while preserving
        chronological order of the non-system messages (oldest to newest).
        """
        max_context_tokens = 7000  # conservative context budget for most models
        reserve_for_reply = max(self.max_tokens + 400, 1000)
        budget = max(2000, max_context_tokens - reserve_for_reply)

        if _messages_token_length(self.encoding, messages) <= budget:
            return messages

        # Separate the first system message (if any) from the rest
        system_msg = next((m for m in messages if m.get("role") == "system"), None)
        non_system_msgs = [m for m in messages if m.get("role") != "system"]

        # Build from the end (most recent first) until budget, then reverse to preserve order
        kept_reversed: List[Dict] = []
        while non_system_msgs:
            candidate = non_system_msgs.pop()  # take last (most recent)
            kept_reversed.append(candidate)

            # Measure if including current kept exceeds budget
            candidate_list: List[Dict] = []
            if system_msg:
                candidate_list.append(system_msg)
            candidate_list.extend(reversed(kept_reversed))  # back to chronological

            if _messages_token_length(self.encoding, candidate_list) > budget:
                kept_reversed.pop()  # remove the last added to stay within budget
                break

        trimmed: List[Dict] = []
        if system_msg:
            trimmed.append(system_msg)
        trimmed.extend(reversed(kept_reversed))
        return trimmed

    @retry(wait=wait_exponential(multiplier=1, min=1, max=10),
           stop=stop_after_attempt(config.OPENAI_RETRY_ATTEMPTS), reraise=True,
           retry=retry_if_exception_type(Exception))
    def generate_reply(self, messages: List[Dict], system_prompt: Optional[str] = None) -> str:
        """
        Generate a reply using OpenAI Chat Completions API.
        `messages` should be a list of {role, content} dicts excluding the system prompt.
        """
        chat_messages: List[Dict] = []
        if system_prompt:
            chat_messages.append({"role": "system", "content": system_prompt})
        chat_messages.extend(messages)

        chat_messages = self._trim_messages_to_fit(chat_messages)

        logger.debug("Submitting to OpenAI with %d messages", len(chat_messages))

        # Rate limit before calling the API
        self._respect_min_interval()

        # Cast messages to expected param type for type-checkers
        typed_messages: Iterable[ChatCompletionMessageParam] = cast(
            Iterable[ChatCompletionMessageParam], chat_messages
        )

        client = self.client.with_options(timeout=self.request_timeout_seconds)
        resp = client.chat.completions.create(
            model=self.model,
            messages=typed_messages,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )
        text = resp.choices[0].message.content or ""
        return text.strip()


def build_engine_from_config() -> GPTEngine:
    return GPTEngine(
        api_key=config.OPENAI_API_KEY,
        model=config.OPENAI_MODEL,
        temperature=config.TEMPERATURE,
        max_tokens=config.MAX_TOKENS,
        request_timeout_seconds=config.REQUEST_TIMEOUT_SECONDS,
    )