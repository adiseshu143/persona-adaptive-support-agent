"""
classifier.py
-------------
Persona detection via Gemini structured output, with a robust keyword fallback.

Personas:
  • Technical Expert   — APIs, configs, error codes, stack traces
  • Frustrated User    — emotional urgency, repeated failures, complaints
  • Business Executive — ROI, timelines, SLA, business impact

The fallback is intentionally designed to be MORE accurate than a simple
keyword count by using TF-weighted scoring and sentence-level signals.
"""

import json
import re

from google.genai import types

from src import config
from src.gemini_utils import get_client, gemini_retry, quota_state, note_failure_if_quota

# ── Keyword lists ─────────────────────────────────────────────────────────────
_TECH_KW = [
    "api", "sdk", "token", "auth", "oauth", "bearer", "endpoint", "webhook",
    "error code", "status code", "401", "403", "404", "500", "503", "timeout",
    "stack trace", "exception", "traceback", "debug", "log", "header",
    "json", "payload", "schema", "migration", "deploy", "server", "database",
    "ssl", "tls", "certificate", "curl", "request", "response", "config",
    "integration", "library", "package", "dependency", "version", "release",
    "null pointer", "memory", "thread", "async", "callback", "promise",
]

_FRUS_KW = [
    "frustrated", "angry", "ridiculous", "unacceptable", "still broken",
    "nothing works", "tried everything", "fed up", "worst", "terrible",
    "fix this now", "not working", "broken again", "waste of time",
    "unbelievable", "pathetic", "useless", "asap", "immediately",
    "how long", "still waiting", "not fixed", "this is a joke",
    "beyond annoying", "completely broken", "hopeless", "sick of this",
    "keep failing", "always fails", "never works",
]

_EXEC_KW = [
    "business impact", "operations", "timeline", "roi", "stakeholders",
    "resolution time", "sla", "uptime", "revenue", "contract",
    "report to", "board", "quarter", "executive", "cost", "budget",
    "productivity", "downtime", "customer churn", "priority",
    "strategic", "competitive", "business continuity", "workforce",
]

# ── Chitchat patterns ─────────────────────────────────────────────────────────
_CHITCHAT = [
    r"^(hi|hello|hey|yo|sup|howdy|hiya)( there| team| folks)?[\s!.,]*$",
    r"^good\s(morning|afternoon|evening|day)[\s!.,]*$",
    r"^(thanks|thank you|thx|ty|cheers|appreciate it)[\s!.,]*$",
    r"^(bye|goodbye|see ya|later|take care)[\s!.,]*$",
    r"^(ok|okay|cool|got it|alright|sure|great|sounds good|perfect)[\s!.,]*$",
    r"^(how are you|what'?s up|how'?s it going)[\s?!.,]*$",
    r"^(yes|no|yep|nope|yeah|nah|maybe)[\s!.,]*$",
    r"^(lol|lmao|haha|hehe|😂|😅|👍|🙏)[\s!.,]*$",
]


def is_chitchat(message: str) -> bool:
    text = message.strip().lower()
    if not text or len(text) <= 2:
        return True
    for pat in _CHITCHAT:
        if re.match(pat, text):
            return True
    return False


# ── Gemini schema ─────────────────────────────────────────────────────────────
_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "persona":    {"type": "STRING", "enum": config.PERSONAS},
        "confidence": {"type": "NUMBER"},
        "reasoning":  {"type": "STRING"},
    },
    "required": ["persona", "confidence", "reasoning"],
}

_SYSTEM = """
You are a precision persona-classification engine for an enterprise AI support desk.

Analyze the message and classify it into EXACTLY ONE of these three personas:

1. "Technical Expert"
   → Uses technical vocabulary: APIs, SDKs, error codes, stack traces, configs.
   → Wants root cause, exact steps, code-level detail.
   → Examples: "My 401 on the /auth endpoint started after upgrading to v3.2",
               "Can you show me the correct OAuth2 PKCE flow?",
               "Stack trace says NullPointerException at line 42."

2. "Frustrated User"
   → Emotional language: urgency, repeated failure, complaints, anger.
   → Uses phrases like "still broken", "nothing works", "I've tried everything".
   → May use ALL CAPS, multiple exclamation marks, or exasperated phrasing.
   → Examples: "WHY IS THIS STILL NOT WORKING???",
               "I've been trying to fix this for 3 hours and nothing helps!",
               "This is completely unacceptable. Fix it NOW."

3. "Business Executive"
   → Outcome-focused: ROI, SLA, timelines, business impact, revenue.
   → Prefers concise answers, not technical deep-dives.
   → Examples: "How does this downtime affect our SLA commitments?",
               "I need to know the business impact and resolution ETA for the board.",
               "What's the cost risk if this isn't resolved by Q3?"

Rules:
- Classify based on the DOMINANT signal, even if signals overlap.
- A person can be frustrated AND technical — choose whichever is STRONGER.
- Confidence must reflect how clearly the message fits (0.3 = ambiguous, 0.95 = obvious).
- Reasoning must be 1-2 sentences explaining WHY you chose this persona.
- Never refuse to classify. Always return a JSON object.
""".strip()


# ── Keyword fallback (accurate heuristic) ─────────────────────────────────────
def _keyword_fallback(message: str) -> dict:
    text   = message.lower()
    words  = set(text.split())
    n_words = max(len(words), 1)

    def score(kw_list):
        # Weight multi-word phrases higher; single keywords lower
        hits = 0
        for kw in kw_list:
            if " " in kw:
                hits += 2 if kw in text else 0
            else:
                hits += 1 if kw in words else 0
        return hits / n_words  # normalise by message length

    scores = {
        "Technical Expert":  score(_TECH_KW),
        "Frustrated User":   score(_FRUS_KW),
        "Business Executive":score(_EXEC_KW),
    }

    # Boosts: strong frustration signals
    if message.count("!") >= 2:
        scores["Frustrated User"] += 0.08
    if re.search(r"\b[A-Z]{4,}\b", message):
        scores["Frustrated User"] += 0.06
    if "???" in message or "!!" in message:
        scores["Frustrated User"] += 0.04
    # Boost: question with technical structure
    if re.search(r"\b(error|exception|code|api|sdk)\b", text) and "?" in message:
        scores["Technical Expert"] += 0.04

    best  = max(scores, key=scores.get)
    total = sum(scores.values())

    if total < 0.01:
        # Nothing matched: guess from surface features
        if "?" in message:
            best = "Technical Expert"
        else:
            best = "Frustrated User"
        return {
            "persona":    best,
            "confidence": 0.35,
            "reasoning":  "Weak signals — guessed from message structure via heuristic fallback.",
        }

    # Confidence: how dominant is the winner?
    dominance  = scores[best] / total
    confidence = round(min(0.4 + 0.5 * dominance, 0.88), 2)

    return {
        "persona":    best,
        "confidence": confidence,
        "reasoning":  f"Keyword fallback: '{best}' had the strongest match signal (normalised score {scores[best]:.3f}).",
    }


# ── Gemini call (retried, shared client) ──────────────────────────────────────
@gemini_retry
def _call_gemini_classify(message: str):
    client = get_client()
    return client.models.generate_content(
        model=config.CLASSIFIER_MODEL,
        contents=message,
        config=types.GenerateContentConfig(
            system_instruction=_SYSTEM,
            response_mime_type="application/json",
            response_schema=_SCHEMA,
            temperature=0.05,   # very low — classification needs determinism
        ),
    )


# ── Public API ────────────────────────────────────────────────────────────────
def classify_persona(message: str) -> dict:
    """
    Returns {"persona": str, "confidence": float, "reasoning": str}.
    Always succeeds — falls back to keyword heuristic on any API failure
    or while Gemini is in a known quota-exhausted cooldown window.
    """
    if not config.GEMINI_API_KEY:
        return _keyword_fallback(message)

    if quota_state.in_cooldown():
        fb = _keyword_fallback(message)
        fb["reasoning"] = (
            "Gemini temporarily skipped (recent quota exhaustion, cooling down). "
            f"Fallback: {fb['reasoning']}"
        )
        return fb

    try:
        response = _call_gemini_classify(message)
        result = json.loads(response.text)

        if result.get("persona") not in config.PERSONAS:
            raise ValueError(f"Unknown persona: {result.get('persona')}")

        result["confidence"] = float(result.get("confidence", 0.5))
        return result

    except Exception as exc:
        note_failure_if_quota(exc)
        fb = _keyword_fallback(message)
        fb["reasoning"] = f"Gemini call failed ({exc}). Fallback: {fb['reasoning']}"
        return fb