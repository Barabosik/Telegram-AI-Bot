# Telegram GPT Persona Bot

A Telegram chatbot that uses GPT (OpenAI API) and can dynamically adopt human personalities on request. It responds to messages like `@Bot act like Einstein and explain relativity` and maintains short-term per-user conversation memory.

## Features
- Responds to prompts starting with `@Bot` in group chats (also recognizes its real `@username` automatically) and to any message in private chats
- Detects persona directives like "act like Einstein" or "pretend you are Shakespeare" and emulates that style
- Per-user conversation memory with a lightweight SQLite database
- Clear commands: `/start`, `/persona`, `/persona clear`, `/reset`
- Modular codebase: `bot.py`, `gpt_engine.py`, `persona_manager.py`, `config.py`

## Setup
1. Clone or copy this project to your machine.
2. Create a Telegram bot via BotFather and get the token.
3. Create an OpenAI API key.
4. Edit `config.py` and set the placeholders:
   - `TELEGRAM_BOT_TOKEN = "YOUR_TELEGRAM_BOT_API_TOKEN"`
   - `OPENAI_API_KEY = "YOUR_OPENAI_API_KEY"`
   - Optionally adjust `OPENAI_MODEL`, `TEMPERATURE`, and other constants.

## Install
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run
```bash
python bot.py
```
The bot uses polling; no webhook setup required for local runs.

## Usage
- In a group: `@Bot act like Socrates and help me think through this decision`.
- In a private chat: `act like Steve Jobs and pitch my app idea`.
- Show persona: `/persona`
- Clear persona: `/persona clear`
- Reset memory: `/reset`

## Notes
- The bot auto-detects its actual `@username` and treats it as a valid mention in addition to the `BOT_MENTION_ALIAS` in `config.py`.
- Memory is limited by `MEMORY_MESSAGE_LIMIT` and trimmed in the GPT engine to stay within context budget.
- For safety, the system prompt instructs the model to refuse unsafe behavior.

## Troubleshooting
- If you see a credentials error, ensure the placeholders in `config.py` are replaced.
- If the bot doesn't answer in a group, make sure you started the message with `@Bot` (or the bot's actual `@username`).
- If OpenAI errors persist, try a different `OPENAI_MODEL` and verify your network connectivity.

## License
MIT