"""
escalator.py
------------
Decides whether a conversation needs human escalation and builds the
structured handoff summary when it does.
"""

import json
from datetime import datetime, timezone

from src import config


def _matched_keywords(message: str) -> list:
    text = message.lower()
    return [kw for kw in config.SENSITIVE_TOPIC_KEYWORDS if kw in text]


def check_escalation(
    user_query: str,
    persona: str,
    context_chunks: list,
    consecutive_frustrated_turns: int = 0,
) -> dict:
    reasons    = []
    best_score = max((c["score"] for c in context_chunks), default=0.0)

    if not context_chunks:
        reasons.append("No relevant documents retrieved from the knowledge base.")
    elif best_score < config.RETRIEVAL_CONFIDENCE_THRESHOLD:
        reasons.append(
            f"Top retrieval confidence ({best_score:.2f}) is below threshold "
            f"({config.RETRIEVAL_CONFIDENCE_THRESHOLD})."
        )

    hits = _matched_keywords(user_query)
    if hits:
        reasons.append("Sensitive topic requiring human review: " + ", ".join(hits[:3]))

    if consecutive_frustrated_turns >= config.MAX_USER_DISSATISFACTION_TURNS:
        reasons.append(
            f"User has shown unresolved frustration for "
            f"{consecutive_frustrated_turns} consecutive turns."
        )

    return {
        "escalate":   len(reasons) > 0,
        "reasons":    reasons,
        "best_score": round(best_score, 4),
    }


def build_handoff_summary(
    user_query: str,
    persona: str,
    context_chunks: list,
    conversation_history: list,
    escalation_check: dict,
    attempted_steps: list = None,
) -> dict:
    attempted_steps = attempted_steps or []
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "persona":       persona,
        "issue_summary": user_query[:280] + ("…" if len(user_query) > 280 else ""),
        "conversation_history": [
            {"role": t.get("role"), "message": t.get("content") or t.get("message", "")}
            for t in conversation_history
        ],
        "retrieved_sources": [
            {"source": c["source"], "page": c.get("page"), "score": c["score"]}
            for c in context_chunks
        ],
        "attempted_steps":      attempted_steps,
        "escalation_reasons":   escalation_check["reasons"],
        "confidence_score":     escalation_check["best_score"],
        "recommended_next_steps": _next_steps(persona, escalation_check),
    }


def _next_steps(persona: str, check: dict) -> str:
    if any("sensitive topic" in r.lower() for r in check["reasons"]):
        return (
            "Route to billing/legal review queue. Verify identity before "
            "discussing account or payment specifics."
        )
    if any("retrieval confidence" in r.lower() or "No relevant documents" in r
           for r in check["reasons"]):
        return (
            "KB did not contain a confident answer. Consider adding a new help "
            "article, and investigate manually."
        )
    if persona == "Business Executive":
        return "Prioritise a fast, concise reply with concrete timelines — executive accounts are impact-sensitive."
    if persona == "Frustrated User":
        return "Lead with empathy and a clear resolution plan; this user has already expressed frustration."
    return "Provide a thorough technical follow-up with full diagnostic detail."