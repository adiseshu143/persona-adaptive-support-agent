"""
escalator.py
------------
Decides whether a conversation should be escalated to a human agent, and
builds the structured handoff summary when it is.

Escalation triggers (configurable in config.py):
  - No relevant documents retrieved
  - Retrieval confidence below threshold
  - Sensitive-topic keywords detected (billing disputes, legal, account
    ownership changes, etc.)
  - Repeated unresolved frustration across consecutive turns
"""

import json
from datetime import datetime, timezone

from src import config


def _matched_sensitive_keywords(message: str) -> list:
    text = message.lower()
    return [kw for kw in config.SENSITIVE_TOPIC_KEYWORDS if kw in text]


def check_escalation(
    user_query: str,
    persona: str,
    context_chunks: list,
    consecutive_frustrated_turns: int = 0,
) -> dict:
    """
    Returns:
        {
            "escalate": bool,
            "reasons": [str, ...],
            "best_score": float,
        }
    """
    reasons = []
    best_score = max((c["score"] for c in context_chunks), default=0.0)

    if not context_chunks:
        reasons.append("No relevant documents were retrieved from the knowledge base.")
    elif best_score < config.RETRIEVAL_CONFIDENCE_THRESHOLD:
        reasons.append(
            f"Top retrieval confidence ({best_score:.2f}) is below the "
            f"configured threshold ({config.RETRIEVAL_CONFIDENCE_THRESHOLD})."
        )

    sensitive_hits = _matched_sensitive_keywords(user_query)
    if sensitive_hits:
        reasons.append(
            "Message touches a sensitive topic requiring human review: "
            + ", ".join(sensitive_hits[:3])
        )

    if consecutive_frustrated_turns >= config.MAX_USER_DISSATISFACTION_TURNS:
        reasons.append(
            f"User has shown unresolved frustration for "
            f"{consecutive_frustrated_turns} consecutive turns."
        )

    return {
        "escalate": len(reasons) > 0,
        "reasons": reasons,
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
    """Builds the structured JSON handoff package for a human agent."""
    attempted_steps = attempted_steps or []

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "persona": persona,
        "issue_summary": user_query[:280] + ("..." if len(user_query) > 280 else ""),
        "conversation_history": [
            {"role": turn.get("role"), "message": turn.get("message")}
            for turn in conversation_history
        ],
        "retrieved_sources": [
            {"source": c["source"], "page": c.get("page"), "score": c["score"]}
            for c in context_chunks
        ],
        "attempted_steps": attempted_steps,
        "escalation_reasons": escalation_check["reasons"],
        "confidence_score": escalation_check["best_score"],
        "recommended_next_steps": _recommend_next_steps(persona, escalation_check),
    }
    return summary


def _recommend_next_steps(persona: str, escalation_check: dict) -> str:
    if any("sensitive topic" in r.lower() for r in escalation_check["reasons"]):
        return (
            "Route to billing/legal review queue. Verify identity before discussing "
            "account or payment specifics."
        )
    if any("retrieval confidence" in r.lower() or "No relevant documents" in r for r in escalation_check["reasons"]):
        return (
            "Knowledge base did not contain a confident answer. Consider whether a "
            "new help-center article is needed, and respond directly with manual "
            "investigation."
        )
    if persona == "Business Executive":
        return "Prioritize a fast, concise reply with concrete timelines — executive accounts are impact-sensitive."
    if persona == "Frustrated User":
        return "Lead with empathy and a clear resolution plan; this user has already expressed frustration."
    return "Provide a thorough technical follow-up with full diagnostic detail."


if __name__ == "__main__":
    chunks = [{"source": "billing_policy.txt", "page": None, "score": 0.3}]
    check = check_escalation("My billing statement has duplicate charges, I demand a refund!", "Frustrated User", chunks)
    print(json.dumps(check, indent=2))
    summary = build_handoff_summary(
        "My billing statement has duplicate charges, I demand a refund!",
        "Frustrated User",
        chunks,
        [{"role": "user", "message": "My billing statement has duplicate charges, I demand a refund!"}],
        check,
    )
    print(json.dumps(summary, indent=2))
