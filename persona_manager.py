import re
from typing import Optional, Tuple

# Predefined persona templates for common requests
_PREDEFINED_PERSONAS = {
    "einstein": (
        "Albert Einstein",
        "Adopt the persona of Albert Einstein. Be insightful, curious, and \
scientifically rigorous. Prefer simple thought experiments to explain ideas. \
Use approachable language while maintaining depth."
    ),
    "shakespeare": (
        "William Shakespeare",
        "Adopt the persona of William Shakespeare. Write with Early Modern \
English flair, iambic rhythm when fitting, and poetic metaphors."
    ),
    "socrates": (
        "Socrates",
        "Adopt the persona of Socrates. Ask probing questions, use the \
Socratic method, and guide the user to clarity through dialogue."
    ),
    "steve jobs": (
        "Steve Jobs",
        "Adopt the persona of Steve Jobs. Be visionary, product-focused, \
minimalist, and persuasive."
    ),
    "tony stark": (
        "Tony Stark",
        "Adopt the persona of Tony Stark. Be witty, confident, and tech-savvy, \
with a dash of humor."
    ),
}

# Regex patterns for persona extraction
_PATTERNS = [
    re.compile(r"\b(act|behave|talk|respond|write)\s+(like|as)\s+([^.,!\n?]+)", re.IGNORECASE),
    re.compile(r"\bpretend\s+(to\s+be|you\s+are)\s+([^.,!\n?]+)", re.IGNORECASE),
    re.compile(r"\bbe\s+([^.,!\n?]+)\b", re.IGNORECASE),
]


def _normalize_persona_name(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip()).lower()


def _persona_from_text(text: str) -> Optional[str]:
    for pattern in _PATTERNS:
        match = pattern.search(text)
        if match:
            # Persona may be in group 2 or 3 depending on pattern
            groups = match.groups()
            # Find the last non-empty group as the persona candidate
            candidate = None
            for g in reversed(groups):
                if isinstance(g, str):
                    g = g.strip()
                    if g and not g.lower() in {"like", "as", "to be", "you are"}:
                        candidate = g
                        break
            if candidate:
                return candidate
    # Also handle leading "as <persona>" fragment
    m = re.match(r"^\s*(as|like)\s+([^.,!\n?]+)", text, re.IGNORECASE)
    if m:
        return m.group(2)
    return None


def _persona_instructions(persona_raw: str) -> Tuple[str, str]:
    norm = _normalize_persona_name(persona_raw)
    # Try exact lookup first, then fuzzy keys contained in the name
    if norm in _PREDEFINED_PERSONAS:
        pretty, system = _PREDEFINED_PERSONAS[norm]
        return pretty, system
    for key, (pretty, system) in _PREDEFINED_PERSONAS.items():
        if key in norm:
            return pretty, system
    # Fallback generic instruction
    pretty = persona_raw.strip()
    system = (
        f"Adopt the persona of {pretty}. Emulate their tone, style, and mannerisms "
        f"while staying accurate, helpful, and safe."
    )
    return pretty, system


def extract_persona_and_clean_text(text: str) -> Tuple[Optional[str], Optional[str], str]:
    """
    Extract persona request and return (persona_name, persona_system_instructions, cleaned_text).
    If no persona is found, persona_name and persona_system_instructions are None.
    The cleaned_text removes leading persona directive fragments that are redundant.
    """
    if not text:
        return None, None, text

    persona_raw = _persona_from_text(text)
    if not persona_raw:
        return None, None, text

    persona_name, persona_sys = _persona_instructions(persona_raw)

    # Remove common directive phrases to clean the user query
    cleaned = re.sub(r"\b(act|behave|talk|respond|write)\s+(like|as)\s+([^.,!\n?]+)\b[:,]?\s*", "", text, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bpretend\s+(to\s+be|you\s+are)\s+([^.,!\n?]+)\b[:,]?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^\s*(as|like)\s+([^.,!\n?]+)\b[:,]?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = cleaned.strip() or f"Respond in the style of {persona_name}."

    return persona_name, persona_sys, cleaned


def build_system_prompt(base_prompt: str, persona_instruction: Optional[str]) -> str:
    if persona_instruction:
        return f"{base_prompt}\n\nPersona:\n{persona_instruction}"
    return base_prompt


def build_vision_system_prompt(base_prompt: str, vision_suffix: str, persona_instruction: Optional[str]) -> str:
    prompt = base_prompt
    if vision_suffix:
        prompt = f"{prompt}\n\nVision:\n{vision_suffix}"
    if persona_instruction:
        prompt = f"{prompt}\n\nPersona:\n{persona_instruction}"
    return prompt