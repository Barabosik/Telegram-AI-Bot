# Configuration for the Telegram GPT Persona Bot
# Fill in the placeholders below before running the bot.

# Telegram and OpenAI credentials (placeholders)
TELEGRAM_BOT_TOKEN = "YOUR_TELEGRAM_BOT_API_TOKEN"
OPENAI_API_KEY = "YOUR_OPENAI_API_KEY"

# Model and generation defaults
OPENAI_MODEL = "gpt-4o-mini"  # e.g., "gpt-4o", "gpt-4o-mini", "gpt-4.1"
TEMPERATURE = 0.7
MAX_TOKENS = 600  # Max tokens for the assistant reply
REQUEST_TIMEOUT_SECONDS = 40

# Rate limiting and retries for OpenAI
OPENAI_MIN_CALL_INTERVAL_SECONDS = 1.0  # enforce a minimum delay between API calls
OPENAI_RETRY_ATTEMPTS = 5  # number of retry attempts on transient errors

# Bot mention alias: messages starting with this will be processed in group chats
# The bot will also accept mentions of its actual @username dynamically.
BOT_MENTION_ALIAS = "@Bot"

# Memory and storage
DB_PATH = "bot_state.sqlite3"
MEMORY_MESSAGE_LIMIT = 10  # Number of recent messages per user to keep in memory context

# Base instructions the assistant always follows. Persona instructions will be appended.
SYSTEM_PROMPT_BASE = (
    "You are a helpful, concise AI assistant for Telegram. "
    "You can adopt specific writing styles or famous personas when asked. "
    "When adopting a persona, emulate their tone, vocabulary, and mannerisms, while maintaining factual accuracy and clarity. "
    "Do not roleplay unsafe or harmful behaviors. If a request is unsafe, refuse politely."
)

# Extra guidance appended for vision/image analysis tasks
VISION_SYSTEM_SUFFIX = (
    "When analyzing images, be robust across screenshots, documents, scenes, memes, and product photos. "
    "Perform OCR when helpful; extract key text succinctly. Identify objects, relationships, and any data or charts. "
    "Summarize with the most important points first, then details. If the user asks a question, answer it directly first. "
    "Flag potential safety issues, sensitive info, or uncertainties. If the image is ambiguous, state reasonable interpretations."
)

# Safety and formatting
REPLY_MAX_CHARS = 3800  # Telegram hard limit ~4096; we keep some headroom