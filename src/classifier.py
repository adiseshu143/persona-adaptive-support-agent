"""
classifier.py
--------------
Persona detection for incoming support messages.

Primary path: ask Gemini for a structured JSON classification
(persona + confidence + reasoning).

Fallback path: if the API call fails (no key configured, network issue,
rate limit, malformed response) we fall back to a lightweight keyword/
heuristic classifier so the rest of the pipeline never breaks just because
classification failed. This keeps the agent demoable offline and resilient
in production.
"""

import json
import re

from google import genai
from google.genai import types

from src import config

_TECH_KEYWORDS = [
    "api", "token", "auth", "config", "endpoint", "error code", "log",
    "stack trace", "header", "json", "webhook", "sdk", "status code",
    "integration", "database", "exception", "401", "403", "500", "timeout",
]

_FRUSTRATED_KEYWORDS = [
    "frustrated", "angry", "ridiculous", "unacceptable", "still broken",
    "nothing works", "tried everything", "fed up", "worst", "terrible",
    "again!!", "asap", "immediately", "demand", "fix this now",
]

_EXEC_KEYWORDS = [
    "business impact", "operations", "timeline", "roi", "stakeholders",
    "resolution time", "sla", "uptime", "revenue", "contract", "leadership",
    "report to", "board", "quarter",
]

_SYSTEM_INSTRUCTION = (
    "You are an advanced classification engine for a customer support platform. "
    "Analyze the sentiment, vocabulary, and tone of an incoming support message "
    "and classify it into exactly one of three customer personas:\n\n"
    "1. 'Technical Expert' -- uses technical terminology, requests logs/APIs/"
    "configurations, wants detailed explanations. Example: \"Can you explain the "
    "API authentication failure and provide error details?\"\n\n"
    "2. 'Frustrated User' -- emotional language, repeated complaints, urgent "
    "requests. Example: \"I've tried everything and nothing works!\"\n\n"
    "3. 'Business Executive' -- outcome-focused, interested in business impact, "
    "prefers concise communication. Example: \"How does this issue impact "
    "operations and when will it be resolved?\"\n\n"
    "Judge the message on its own merits using these three definitions. Respond "
    "strictly in the requested JSON structure. Confidence is a float between 0 and 1."
)

_CHITCHAT_PATTERNS = [
    r"^(hi|hello|hey|yo|sup|howdy|hiya)( there| team| folks)?[\s!.,]*$",
    r"^good\s(morning|afternoon|evening|day)[\s!.,]*$",
    r"^(thanks|thank you|thx|ty|cheers|appreciate it|appreciate you)[\s!.,]*$",
    r"^(bye|goodbye|see ya|see you|later|take care)[\s!.,]*$",
    r"^(ok|okay|cool|got it|alright|sure|great|nice|sounds good|perfect)[\s!.,]*$",
    r"^(how are you|what'?s up|how'?s it going)[\s?!.,]*$",
    r"^(yes|no|yep|nope|yeah|nah|maybe)[\s!.,]*$",
]


def is_chitchat(message: str) -> bool:
    """True for greetings, small talk, or acknowledgements with no support
    content. These should never be forced through persona-based escalation
    logic -- there's nothing to classify or retrieve documents for."""
    text = message.strip().lower()
    if not text or len(text) <= 2:
        return True
    for pattern in _CHITCHAT_PATTERNS:
        if re.match(pattern, text):
            return True
    return False

_RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "persona": {
            "type": "STRING",
            "enum": config.PERSONAS,
        },
        "confidence": {"type": "NUMBER"},
        "reasoning": {"type": "STRING"},
    },
    "required": ["persona", "confidence", "reasoning"],
}


def _keyword_fallback(message: str) -> dict:
    """Deterministic rule-based classifier used when the LLM call fails."""
    text = message.lower()

    scores = {
        "Technical Expert": sum(1 for kw in _TECH_KEYWORDS if kw in text),
        "Frustrated User": sum(1 for kw in _FRUSTRATED_KEYWORDS if kw in text),
        "Business Executive": sum(1 for kw in _EXEC_KEYWORDS if kw in text),
    }

    # Exclamation marks and ALL-CAPS words are strong frustration signals.
    if message.count("!") >= 1:
        scores["Frustrated User"] += 1
    if re.search(r"\b[A-Z]{4,}\b", message):
        scores["Frustrated User"] += 1

    persona = max(scores, key=scores.get)
    total = sum(scores.values())

    if total == 0:
        # No strong signal either way; default to the calmer, most common case.
        return {
            "persona": "Frustrated User" if "?" not in message else "Technical Expert",
            "confidence": 0.35,
            "reasoning": "No strong lexical signal detected; defaulted via heuristic fallback.",
        }

    confidence = min(0.55 + 0.1 * scores[persona], 0.9)
    return {
        "persona": persona,
        "confidence": round(confidence, 2),
        "reasoning": f"Keyword fallback matched {scores[persona]} '{persona}' signal(s) in the message.",
    }


def classify_persona(message: str) -> dict:
    """
    Classify a user message into one of config.PERSONAS.

    Returns:
        {"persona": str, "confidence": float, "reasoning": str}
    """
    if not config.GEMINI_API_KEY:
        return _keyword_fallback(message)

    try:
        client = genai.Client(api_key=config.GEMINI_API_KEY)
        response = client.models.generate_content(
            model=config.CLASSIFIER_MODEL,
            contents=message,
            config=types.GenerateContentConfig(
                system_instruction=_SYSTEM_INSTRUCTION,
                response_mime_type="application/json",
                response_schema=_RESPONSE_SCHEMA,
                temperature=0.1,
            ),
        )
        result = json.loads(response.text)

        # Defensive validation -- never trust the model blindly.
        if result.get("persona") not in config.PERSONAS:
            raise ValueError("Model returned an unsupported persona label.")
        result["confidence"] = float(result.get("confidence", 0.5))
        return result

    except Exception as exc:  # noqa: BLE001 -- intentionally broad: any failure -> fallback
        fallback = _keyword_fallback(message)
        fallback["reasoning"] = f"LLM classification failed ({exc}); used fallback. {fallback['reasoning']}"
        return fallback


if __name__ == "__main__":
    samples = [
        "Where is the guide to clear cookies? It's been an hour and nothing is loading on your interface!",
        "What are the header parameter requirements for your bearer token auth implementation?",
        "Our operational uptime is decreasing. We need a timeline of when billing disputes are resolved.",
    ]
    for s in samples:
        print(s)
        print(json.dumps(classify_persona(s), indent=2))
        print("-" * 60)
