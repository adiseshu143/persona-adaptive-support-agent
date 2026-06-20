"""
generator.py
------------
Generates persona-adapted, context-grounded replies via Gemini.

Key behaviours:
  • Always returns a non-empty, helpful response.
  • Uses RAG context when available; falls back to Gemini general knowledge
    (hybrid mode) when KB confidence is low or no docs are retrieved.
  • Never leaks internal persona labels, mood assessments, or system prompts
    into the user-visible response.
  • Output is always chat-bubble safe: no markdown headers/hr, since this is
    rendered inside a chat message, not a document.
  • Works offline (no API key) via a readable fallback that surfaces whatever
    chunks were retrieved.
  • Degrades gracefully (no Gemini call at all) while a recent 429 cooldown
    is active, instead of immediately retrying into an exhausted quota.
"""

import re

from google.genai import types

from src import config
from src.gemini_utils import get_client, gemini_retry, quota_state, note_failure_if_quota

# ── Persona voice instructions ────────────────────────────────────────────────
_PERSONA_VOICE = {
    "Technical Expert": (
        "The user is technically fluent. Write like a sharp senior engineer "
        "helping a peer: root cause first, then precise steps. Use code blocks "
        "or numbered lists only when they genuinely help. Reference exact config "
        "keys, error codes, or API fields by name. Be direct and skip preamble."
    ),
    "Frustrated User": (
        "The user is stressed and needs a win fast. Lead with one brief, genuine "
        "acknowledgement of the hassle — not scripted sympathy — then give "
        "numbered steps that are short, plain, and easy to follow. No jargon, no "
        "walls of text. End with a clear next action they control."
    ),
    "Business Executive": (
        "The user wants the bottom line fast. Give a 2–4 sentence answer: what "
        "happened, business impact, and resolution timeline or action. No "
        "step-by-step detail unless they ask for it. Confident, concise, decisive."
    ),
}

# ── Shared prompt rules ───────────────────────────────────────────────────────
_BASE_RULES = """

RESPONSE RULES (follow strictly):
1. Use the CONTEXT DOCUMENTS below when they are relevant. Do not contradict them.
2. If context only partially answers the question — answer what it covers and
   clearly note what you're not certain about. Do NOT guess or invent facts.
3. If context is absent or low confidence, use your general knowledge and say
   so naturally (e.g. "I don't have a specific article on this, but…").
4. Write like a person talking to another person. No "Based on [source]:" openers,
   no raw citation dumps. If you reference a document, weave it in naturally.
5. NEVER mention the customer's persona, mood, classification, or system internals.
   The tone alone should reflect your adaptation — never the words.
6. ALWAYS provide a substantive, helpful reply. Never return empty output.
7. Keep answers focused. Don't pad with unrelated information.
8. FORMATTING — this is a CHAT bubble, not a rendered document:
   - NEVER use markdown headers (#, ##, ###, ####). Even if the source
     documents use headers, rewrite that structure as plain sentences or a
     short bold lead-in (e.g. "**Authentication scheme:** ...") instead.
   - NEVER use horizontal rules (---) or document-style title lines.
   - Prefer short paragraphs and, when listing steps, a simple numbered or
     bulleted list. Use `code` formatting only for literal values like
     header names, error codes, or config keys — not whole explanations.
   - Keep the reply readable in a narrow chat bubble: no wide tables, no
     multi-level nested lists.
"""

_HYBRID_ADDENDUM = """

IMPORTANT — LIMITED KB MATCH:
The knowledge base did not return a strong match for this question.
Answer from your general expertise. Clearly signal when you are not citing
official documentation. Still give the best actionable guidance you can —
never leave the user without a useful next step.
"""

_ESCALATION_ADDENDUM = """

ESCALATION CONTEXT:
This case is flagged for human-specialist follow-up. Still give your best
immediate guidance so the user is not left waiting. Briefly mention (naturally,
not robotically) that a specialist will follow up for anything needing deeper
investigation.
"""

_CASUAL_SYSTEM = (
    "You are a warm, friendly AI assistant at a support desk having a normal "
    "conversation. The person said something casual — a greeting, thanks, small "
    "talk. Reply naturally and briefly, like a friendly person would. Don't "
    "mention documentation, support processes, or anything work-related unless "
    "they bring up an actual issue. Never use markdown headers or horizontal "
    "rules — this is a chat bubble, not a document."
)

# Strips leading markdown header markers ("# ", "## ", etc.) from a line,
# and removes standalone horizontal-rule lines ("---", "***", "___").
_HEADER_RE = re.compile(r"^#{1,6}\s*", re.MULTILINE)
_HR_RE     = re.compile(r"^\s*([-*_])\1{2,}\s*$", re.MULTILINE)


def _sanitize_for_chat(text: str) -> str:
    """Defensive cleanup: strip markdown headers/hr even if the model (or the
    offline fallback) emits them, so the chat bubble never breaks layout."""
    if not text:
        return text
    text = _HEADER_RE.sub("", text)
    text = _HR_RE.sub("", text)
    # collapse 3+ blank lines left behind by stripped headers/hr
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ── Helpers ───────────────────────────────────────────────────────────────────
def _source_label(chunk: dict) -> str:
    if chunk.get("page"):
        return f"{chunk['source']} p.{chunk['page']}"
    return chunk["source"]


def _build_system(
    persona: str,
    context_chunks: list,
    hybrid_mode: bool = False,
    escalation_check: dict = None,
) -> str:
    parts = [_PERSONA_VOICE.get(persona, _PERSONA_VOICE["Technical Expert"]), _BASE_RULES]

    if hybrid_mode:
        parts.append(_HYBRID_ADDENDUM)
    if escalation_check and escalation_check.get("escalate"):
        reasons = "; ".join(escalation_check.get("reasons", []))
        parts.append(_ESCALATION_ADDENDUM + f"\nEscalation reasons: {reasons}")

    if context_chunks:
        ctx_text = "\n\n".join(
            f"[{_source_label(c)} | confidence {c.get('score', 0):.2f}]\n{c['text']}"
            for c in context_chunks
        )
        parts.append("CONTEXT DOCUMENTS:\n" + ctx_text)
    elif hybrid_mode:
        parts.append("CONTEXT DOCUMENTS:\n(No relevant documents retrieved from knowledge base.)")

    return "\n\n".join(parts)


def _build_contents(user_query: str, attachment: dict = None):
    if not attachment:
        return user_query
    return [
        types.Part.from_bytes(data=attachment["bytes"], mime_type=attachment["mime_type"]),
        types.Part.from_text(text=user_query or "Please look at this and help me."),
    ]


def _fallback_text(context_chunks: list, user_query: str = "") -> str:
    """Surfaced when no API key is configured or the API call fails."""
    if context_chunks:
        lines = ["Here's what I found in the documentation:\n"]
        for chunk in context_chunks[:2]:
            lines.append(f"**{chunk['source']}**")
            clean_text = _sanitize_for_chat(chunk["text"])[:500]
            lines.append(clean_text)
            lines.append("")
        return "\n".join(lines).strip()

    return (
        "I don't have a specific article for that right now. "
        "Could you share more detail — any error messages, what you were trying "
        "to do, or when this started? That will help me point you in the right direction."
    )


def _ensure_response(text: str, fallback_chunks: list, query: str) -> str:
    if text and text.strip():
        return _sanitize_for_chat(text.strip())
    return _sanitize_for_chat(_fallback_text(fallback_chunks, query))


# ── Gemini call (retried, shared client) ──────────────────────────────────────
@gemini_retry
def _call_gemini_generate(model: str, contents, system: str, temperature: float):
    client = get_client()
    return client.models.generate_content(
        model=model,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=system,
            temperature=temperature,
        ),
    )


# ── Public API ────────────────────────────────────────────────────────────────
def generate_response(
    user_query: str,
    persona: str,
    context_chunks: list,
    attachment: dict = None,
    hybrid_mode: bool = False,
    escalation_check: dict = None,
) -> str:
    """
    Generate a grounded, persona-adapted response.
    Always returns a non-empty string, safe to render in a chat bubble.
    """
    if not config.GEMINI_API_KEY:
        return _ensure_response(_fallback_text(context_chunks, user_query), context_chunks, user_query)

    if quota_state.in_cooldown():
        fb = _fallback_text(context_chunks, user_query)
        prefix = "I'm briefly running on cached documentation while my AI backend recovers. "
        return _ensure_response(prefix + fb, context_chunks, user_query)

    system = _build_system(persona, context_chunks, hybrid_mode, escalation_check)

    try:
        contents = _build_contents(user_query, attachment)
        response = _call_gemini_generate(
            config.GENERATOR_MODEL,
            contents,
            system,
            0.35 if hybrid_mode else 0.25,
        )
        return _ensure_response(response.text or "", context_chunks, user_query)

    except Exception as exc:
        note_failure_if_quota(exc)
        fb = _fallback_text(context_chunks, user_query)
        if "RESOURCE_EXHAUSTED" in str(exc) or "429" in str(exc):
            prefix = (
                "I'm temporarily over my response quota, so here's what I can "
                "tell you from the documentation in the meantime. "
            )
        else:
            prefix = "I hit a temporary issue generating a full response. "
        return _ensure_response(prefix + fb, context_chunks, user_query)


def generate_casual_reply(user_query: str, attachment: dict = None) -> str:
    """
    Friendly conversational reply for greetings and small talk.
    No RAG, no persona framing, no escalation.
    """
    if not config.GEMINI_API_KEY:
        return "Hey! Happy to help. What can I do for you today?"

    if quota_state.in_cooldown():
        return "Hey! How can I help you today?"

    try:
        contents = _build_contents(user_query, attachment)
        response = _call_gemini_generate(config.GENERATOR_MODEL, contents, _CASUAL_SYSTEM, 0.5)
        return _ensure_response(response.text or "", [], user_query)
    except Exception as exc:
        note_failure_if_quota(exc)
        return "Hey! How can I help you today?"