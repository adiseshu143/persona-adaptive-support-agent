"""
generator.py
------------
Builds persona-specific system prompts grounded strictly in retrieved
context, and calls Gemini to produce the final customer-facing response.

If escalation has already been triggered upstream, this module is not
called for generation -- the caller should use escalator.build_handoff_summary
instead and show the canned escalation message.
"""

from google import genai
from google.genai import types

from src import config

_PERSONA_INSTRUCTIONS = {
    "Technical Expert": (
        "You're chatting with someone technical who wants the real details -- "
        "root cause, exact config/error-code specifics, step-by-step fix. Write "
        "like a sharp colleague helping out, not a manual. Use code blocks or "
        "numbered steps where they genuinely help. Be direct and precise."
    ),
    "Frustrated User": (
        "You're chatting with someone who's had a rough time with this. Sound "
        "like a person who actually cares, not a script -- a brief, genuine, "
        "specific acknowledgement of the hassle is fine, but don't overdo it. "
        "Then give clear, simple, easy-to-follow steps. No jargon."
    ),
    "Business Executive": (
        "You're chatting with someone who wants the bottom line fast -- the "
        "answer, the impact, the timeline. Keep it tight, skip step-by-step "
        "detail unless asked. A few short, confident sentences."
    ),
}

_CASUAL_INSTRUCTIONS = (
    "You're a warm, easygoing AI assistant for a support desk having a normal "
    "conversation -- the person just said something casual (a greeting, thanks, "
    "small talk) rather than asking a support question. Reply naturally and "
    "briefly, the way a friendly person would. Don't mention documentation, "
    "personas, escalation, or anything support-process related unless they "
    "bring up an actual issue."
)

_GROUNDING_RULES = (
    "\n\nIMPORTANT GROUND RULES:\n"
    "- Answer using the FACTUAL CONTEXT DOCUMENTS below -- don't invent steps, "
    "policies, or numbers that aren't in them.\n"
    "- If the context only partly covers the question, answer what it covers "
    "and say plainly what you're not certain about -- don't guess at the rest.\n"
    "- Write like a person talking to another person: natural, warm, plain "
    "English. No 'Based on [document]:' openers, no dumping raw citations, no "
    "rigid template structure. If you reference a source, weave it in "
    "naturally (e.g. 'our password reset guide says...').\n"
    "- NEVER mention the customer's persona, mood, or how you classified them "
    "(no 'as a frustrated user', 'since you're an executive', 'based on your "
    "frustration', etc.). Just talk to them like a person -- the tone should "
    "show it, not the words."
)


def _format_source_label(chunk: dict) -> str:
    if chunk.get("page"):
        return "{} p.{}".format(chunk["source"], chunk["page"])
    return chunk["source"]


def _build_system_prompt(persona: str, context_chunks: list) -> str:
    persona_instructions = _PERSONA_INSTRUCTIONS.get(persona, _PERSONA_INSTRUCTIONS["Technical Expert"])
    context_text = "\n\n".join(
        "Source [{}]: {}".format(_format_source_label(c), c["text"])
        for c in context_chunks
    )
    return "{}{}\n\nFACTUAL CONTEXT DOCUMENTS:\n{}".format(persona_instructions, _GROUNDING_RULES, context_text)


def generate_response(user_query: str, persona: str, context_chunks: list, attachment: dict = None) -> str:
    """Generates the grounded, persona-adapted reply. Assumes the caller has
    already confirmed escalation is NOT required.

    attachment, if provided, is {"bytes": <raw bytes>, "mime_type": <str>} for
    an uploaded image or document the customer wants the model to look at
    alongside their question.
    """
    system_prompt = _build_system_prompt(persona, context_chunks)

    if not config.GEMINI_API_KEY:
        return _offline_fallback_response(context_chunks)

    try:
        client = genai.Client(api_key=config.GEMINI_API_KEY)
        contents = _build_contents(user_query, attachment)
        response = client.models.generate_content(
            model=config.GENERATOR_MODEL,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=0.3,
            ),
        )
        return response.text
    except Exception as exc:  # noqa: BLE001
        return (
            "I ran into a temporary issue generating a full response ({}). "
            "Here is the most relevant documentation I found:\n\n{}"
        ).format(exc, _offline_fallback_response(context_chunks))


def generate_casual_reply(user_query: str, attachment: dict = None) -> str:
    """Friendly free-chat reply for greetings/small talk -- no KB context,
    no persona framing, no escalation logic. Just a normal conversational
    response, the way ChatGPT/Claude/Gemini would handle small talk."""
    if not config.GEMINI_API_KEY:
        return "Hey! How can I help you today?"

    try:
        client = genai.Client(api_key=config.GEMINI_API_KEY)
        contents = _build_contents(user_query, attachment)
        response = client.models.generate_content(
            model=config.GENERATOR_MODEL,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=_CASUAL_INSTRUCTIONS,
                temperature=0.5,
            ),
        )
        return response.text
    except Exception:
        return "Hey! How can I help you today?"


def _build_contents(user_query: str, attachment: dict = None):
    """Builds the `contents` payload for the Gemini call, attaching an
    image/document part when the customer uploaded one."""
    if not attachment:
        return user_query

    return [
        types.Part.from_bytes(data=attachment["bytes"], mime_type=attachment["mime_type"]),
        types.Part.from_text(text=user_query or "Please take a look at this and help me with it."),
    ]


def _offline_fallback_response(context_chunks: list) -> str:
    """Used only when no API key is configured -- surfaces retrieved context
    directly so the app remains demoable without live model calls."""
    if not context_chunks:
        return "No relevant documentation was found for this question."
    lines = ["Based on {}:".format(context_chunks[0]["source"]), ""]
    lines.append(context_chunks[0]["text"][:600])
    return "\n".join(lines)


if __name__ == "__main__":
    sample_chunks = [{
        "source": "password_reset_guide.pdf",
        "page": 1,
        "text": "Reset links are single-use and expire after 30 minutes for security.",
        "score": 0.8,
    }]
    print(generate_response("How long is my reset link valid?", "Technical Expert", sample_chunks))

