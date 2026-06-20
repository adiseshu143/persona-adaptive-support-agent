"""
app.py
------
Persona-Adaptive Support Desk — Streamlit front-end.

Run:  streamlit run app.py
"""
import os
import sys
import json
import html
import inspect
from datetime import datetime

import streamlit as st
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src import config, classifier, generator, escalator
from src.classifier import is_chitchat
from src.rag_pipeline import RAGPipeline
from src.gemini_utils import quota_state

if not config.GEMINI_API_KEY:
    st.error("GEMINI_API_KEY not found in environment.")

# ── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Persona-Adaptive Support Desk",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="auto",
)

_CSS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "style.css")
with open(_CSS_PATH, "r", encoding="utf-8") as _f:
    st.markdown(f"<style>{_f.read()}</style>", unsafe_allow_html=True)


# ── Pipeline (cached) ─────────────────────────────────────────────────────────
@st.cache_resource(show_spinner=False)
def get_pipeline():
    pipeline   = RAGPipeline()
    ingest_result = None
    ingest_error  = None
    if pipeline.collection.count() == 0:
        try:
            ingest_result = pipeline.ingest_documents()
        except Exception as exc:
            ingest_error = str(exc)
    return pipeline, ingest_result, ingest_error


pipeline, ingest_result, ingest_error = get_pipeline()


# ── Session state ─────────────────────────────────────────────────────────────
def _init_state():
    defaults = {
        "messages":               [],
        "consecutive_frustrated": 0,
        "last_insight":           None,
        "persona_counts":         {p: 0 for p in config.PERSONAS},
        "escalation_count":       0,
        "total_turns":            0,
        "pending_response":       False,
        "pending_prompt":         None,
        "pending_attachment":     None,
        "pending_attachment_name":None,
        "uploader_key":           0,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


_init_state()


# ── Render helpers ────────────────────────────────────────────────────────────
_BADGE_CLASS = {
    "Technical Expert":  "badge-tech",
    "Frustrated User":   "badge-frustrated",
    "Business Executive":"badge-executive",
}
_METER_COLOR = {
    "Technical Expert":  "var(--tech-text)",
    "Frustrated User":   "var(--frus-text)",
    "Business Executive":"var(--exec-text)",
}


def persona_badge_html(persona: str, active: bool = False) -> str:
    cls   = _BADGE_CLASS.get(persona, "badge-tech")
    icon  = config.PERSONA_ICON.get(persona, "")
    extra = " badge-active" if active else ""
    return f'<span class="psa-badge {cls}{extra}">{icon} {persona}</span>'


def confidence_meter_html(score: float, color: str) -> str:
    pct = max(0, min(100, round(score * 100)))
    return (
        '<div class="psa-meter-row">'
        f'<div class="psa-meter-track">'
        f'<div class="psa-meter-fill" style="width:{pct}%;background:{color};"></div>'
        f'</div>'
        f'<div class="psa-meter-label">{pct}%</div>'
        '</div>'
    )


def source_chip_html(chunk: dict) -> str:
    page    = f" · p.{chunk['page']}" if chunk.get("page") else ""
    snippet = chunk["text"].strip().replace("\n", " ")
    if len(snippet) > 150:
        snippet = snippet[:150] + "…"
    return (
        '<div class="psa-source">'
        f'<div class="fname">{chunk["source"]}{page} — {chunk["score"]:.2f}</div>'
        f'<div class="snippet">{html.escape(snippet)}</div>'
        '</div>'
    )


def _truncate(text: str, limit: int = 200) -> str:
    safe = html.escape(text or "")
    return safe[:limit] + "…" if len(safe) > limit else safe


# ── Message rendering ─────────────────────────────────────────────────────────
def render_messages(container, messages, show_typing: bool = False):
    with container:
        if not messages and not show_typing:
            st.markdown(
                '<div class="psa-chat-empty">'
                '<span class="psa-chat-empty-icon">💬</span>'
                '<div class="psa-chat-empty-title">Start a conversation</div>'
                '<div class="psa-chat-empty-sub">'
                'Ask about API errors, billing issues, product features,<br>'
                'or anything else — I adapt to how you communicate.'
                '</div>'
                '</div>',
                unsafe_allow_html=True,
            )
        for msg in messages:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])
                if msg.get("attachment_name"):
                    st.caption(f"📎 {msg['attachment_name']}")
        if show_typing:
            with st.chat_message("assistant"):
                st.markdown(
                    '<div class="typing-indicator">'
                    '<span></span><span></span><span></span>'
                    '</div>',
                    unsafe_allow_html=True,
                )


# ── Response generation ───────────────────────────────────────────────────────
def _process_pending_response():
    """Generate and commit the assistant reply for a pending user message."""
    prompt     = st.session_state.pending_prompt
    attachment = st.session_state.pending_attachment

    chitchat = is_chitchat(prompt) and attachment is None

    if chitchat:
        response_text    = generator.generate_casual_reply(prompt)
        escalation_check = {"escalate": False, "reasons": [], "best_score": 0.0}
        context_chunks   = []
        handoff          = None
        persona_result   = None
    else:
        persona_result = classifier.classify_persona(prompt)
        persona        = persona_result["persona"]

        if persona == "Frustrated User":
            st.session_state.consecutive_frustrated += 1
        else:
            st.session_state.consecutive_frustrated = 0

        context_chunks   = pipeline.retrieve_context(prompt)
        escalation_check = escalator.check_escalation(
            user_query=prompt,
            persona=persona,
            context_chunks=context_chunks,
            consecutive_frustrated_turns=st.session_state.consecutive_frustrated,
        )

        best_score  = escalation_check["best_score"]
        hybrid_mode = (not context_chunks or best_score < config.RETRIEVAL_CONFIDENCE_THRESHOLD)

        handoff = None
        if escalation_check["escalate"]:
            handoff = escalator.build_handoff_summary(
                user_query=prompt,
                persona=persona,
                context_chunks=context_chunks,
                conversation_history=st.session_state.messages,
                escalation_check=escalation_check,
            )

        # Forward only kwargs that the current generator signature accepts
        gen_kwargs = {"hybrid_mode": hybrid_mode, "escalation_check": escalation_check}
        accepted   = inspect.signature(generator.generate_response).parameters
        gen_kwargs = {k: v for k, v in gen_kwargs.items() if k in accepted}

        response_text = generator.generate_response(
            prompt, persona, context_chunks, attachment, **gen_kwargs
        )

    # Commit
    st.session_state.messages.append({"role": "assistant", "content": response_text})

    if not chitchat:
        st.session_state.persona_counts[persona] = (
            st.session_state.persona_counts.get(persona, 0) + 1
        )
        st.session_state.total_turns += 1
        if escalation_check["escalate"]:
            st.session_state.escalation_count += 1

        st.session_state.last_insight = {
            "persona":          persona,
            "confidence":       persona_result["confidence"],
            "reasoning":        persona_result.get("reasoning", ""),
            "context_chunks":   context_chunks,
            "escalation_check": escalation_check,
            "handoff":          handoff,
        }
    else:
        st.session_state.last_insight = {"casual": True}

    # Clear pending
    st.session_state.pending_response        = False
    st.session_state.pending_prompt          = None
    st.session_state.pending_attachment      = None
    st.session_state.pending_attachment_name = None


# ── Chat column ───────────────────────────────────────────────────────────────
def render_chat_area():
    st.markdown(
        '<div class="psa-chat-header">'
        '<div class="psa-chat-header-dot"></div>'
        'AI Chat'
        '</div>',
        unsafe_allow_html=True,
    )

    chat_container = st.container(height=500, border=False)

    if st.session_state.pending_response:
        render_messages(chat_container, st.session_state.messages, show_typing=True)
        _process_pending_response()
        st.rerun()
    else:
        render_messages(chat_container, st.session_state.messages, show_typing=False)

    # Input row: attach button | text + send
    attach_col, form_col = st.columns([0.07, 0.93], gap="small", vertical_alignment="center")

    with attach_col:
        with st.popover("📎", help="Attach a file"):
            uploaded_file = st.file_uploader(
                "Upload",
                label_visibility="collapsed",
                key=f"uploader_{st.session_state.uploader_key}",
            )

    with form_col:
        with st.form("psa_chat_form", clear_on_submit=True, border=False):
            text_col, send_col = st.columns([0.9, 0.1], gap="small", vertical_alignment="center")
            with text_col:
                prompt = st.text_input(
                    "Message",
                    placeholder="Ask anything — I'll adapt to you...",
                    label_visibility="collapsed",
                )
            with send_col:
                submitted = st.form_submit_button("➤", use_container_width=True)

    if submitted and prompt and prompt.strip():
        attachment      = None
        attachment_name = None
        if uploaded_file is not None:
            attachment = {
                "bytes":     uploaded_file.getvalue(),
                "mime_type": uploaded_file.type or "application/octet-stream",
            }
            attachment_name = uploaded_file.name
            st.session_state.uploader_key += 1

        st.session_state.messages.append({
            "role":            "user",
            "content":         prompt.strip(),
            "attachment_name": attachment_name,
        })
        st.session_state.pending_response        = True
        st.session_state.pending_prompt          = prompt.strip()
        st.session_state.pending_attachment      = attachment
        st.session_state.pending_attachment_name = attachment_name
        st.rerun()


# ── Insights panel ────────────────────────────────────────────────────────────
def render_insights_panel():
    st.markdown('<div class="psa-insights-header">Case Insights</div>', unsafe_allow_html=True)

    insight = st.session_state.last_insight

    if insight is None:
        st.markdown(
            '<div class="psa-card">'
            '<div class="psa-card-title">Awaiting input</div>'
            '<div class="psa-card-placeholder">'
            'Send a message to see live persona detection, retrieved sources, '
            'and escalation status here.'
            '</div></div>',
            unsafe_allow_html=True,
        )
        return

    if insight.get("casual"):
        st.markdown(
            '<div class="psa-card">'
            '<div class="psa-card-title">Casual exchange</div>'
            '<div class="psa-card-placeholder">'
            'That was small talk — no classification needed. '
            'Ask a support question to see the full breakdown.'
            '</div></div>',
            unsafe_allow_html=True,
        )
        return

    persona = insight["persona"]

    # Persona card
    st.markdown(
        f'<div class="psa-card">'
        f'<div class="psa-card-title">Detected Persona</div>'
        f'{persona_badge_html(persona, active=True)}'
        f'{confidence_meter_html(insight["confidence"], _METER_COLOR.get(persona, "var(--violet-light)"))}'
        f'<div class="psa-reasoning">{_truncate(insight.get("reasoning", ""), 220)}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # Sources card
    sources_html = "".join(source_chip_html(c) for c in insight["context_chunks"])
    if not sources_html:
        sources_html = (
            '<div style="font-size:0.78rem;color:var(--text-dim);">'
            'No KB match — answered from general knowledge.'
            '</div>'
        )
    st.markdown(
        f'<div class="psa-card">'
        f'<div class="psa-card-title">Retrieved Sources</div>'
        f'{sources_html}'
        f'</div>',
        unsafe_allow_html=True,
    )

    # Download buttons
    seen = []
    for c in insight["context_chunks"]:
        if c["source"] in seen:
            continue
        seen.append(c["source"])
        fp = os.path.join(config.DATA_DIR, c["source"])
        if os.path.isfile(fp):
            with open(fp, "rb") as fh:
                st.download_button(
                    label=f"⬇ {c['source']}",
                    data=fh.read(),
                    file_name=c["source"],
                    key=f"dl_{c['source']}_{len(st.session_state.messages)}",
                    use_container_width=True,
                )

    # Escalation card
    esc           = insight["escalation_check"]
    status_class  = "status-escalated" if esc["escalate"] else "status-ok"
    status_label  = "⚠ ESCALATED" if esc["escalate"] else "✓ RESOLVED"
    reasons_html  = "".join(
        f'<li>{html.escape(r)}</li>' for r in esc["reasons"]
    )
    reasons_block = (
        f'<ul class="psa-escalation-reasons">{reasons_html}</ul>'
        if reasons_html else ""
    )
    st.markdown(
        f'<div class="psa-card">'
        f'<div class="psa-card-title">Escalation Status</div>'
        f'<span class="psa-status {status_class}">{status_label}</span>'
        f'{reasons_block}'
        f'</div>',
        unsafe_allow_html=True,
    )

    # Handoff JSON
    if insight.get("handoff"):
        with st.expander("Human handoff package", expanded=False):
            st.code(json.dumps(insight["handoff"], indent=2), language="json")


# ── Analytics ─────────────────────────────────────────────────────────────────
def render_analytics(in_expander: bool = False):
    total = st.session_state.total_turns
    escs  = st.session_state.escalation_count
    rate  = round(100 * escs / total) if total else 0

    st.markdown(
        f'''<div class="psa-analytics-grid">
          <div class="psa-metric-tile">
            <div class="psa-metric-value">{total}</div>
            <div class="psa-metric-label">Turns</div>
          </div>
          <div class="psa-metric-tile">
            <div class="psa-metric-value">{escs}</div>
            <div class="psa-metric-label">Escalated</div>
          </div>
          <div class="psa-metric-tile">
            <div class="psa-metric-value">{rate}%</div>
            <div class="psa-metric-label">Rate</div>
          </div>
        </div>''',
        unsafe_allow_html=True,
    )

    df = pd.DataFrame({
        "Persona":  list(st.session_state.persona_counts.keys()),
        "Messages": list(st.session_state.persona_counts.values()),
    }).set_index("Persona")

    if not in_expander:
        st.markdown(
            '<div class="psa-card"><div class="psa-card-title">Persona Distribution</div></div>',
            unsafe_allow_html=True,
        )
    st.bar_chart(df, color="#7C3AED")


# ── LEFT SIDEBAR ──────────────────────────────────────────────────────────────
with st.sidebar:

    # Brand
    st.markdown(
        '''<div class="psa-brand">
          <div class="psa-brand-mark">AS</div>
          <div class="psa-brand-name">Persona-Adaptive<br>Support Desk</div>
          <div class="psa-brand-sub">Enterprise AI Support</div>
        </div>''',
        unsafe_allow_html=True,
    )

    # Knowledge Base
    st.markdown('<span class="psa-section-label">Knowledge Base</span>', unsafe_allow_html=True)

    if ingest_error:
        st.error(f"Ingestion failed: {ingest_error}")
    elif ingest_result and ingest_result.get("files_found", 0) > 0 and ingest_result.get("chunks_indexed", 0) == 0:
        st.warning("Files found but 0 chunks indexed. Try rebuilding.")

    chunk_count   = pipeline.collection.count()
    idx_ok        = chunk_count > 0
    status_class  = "" if idx_ok else " warn"
    status_label  = "Indexed & ready" if idx_ok else "Empty — rebuild required"

    st.markdown(
        f'''<div class="psa-stat-tile">
          <div class="psa-stat-icon">🗄️</div>
          <div>
            <div class="psa-stat-value">{chunk_count}</div>
            <div class="psa-stat-label">Chunks indexed</div>
          </div>
        </div>
        <div class="psa-index-status{status_class}">● {status_label}</div>''',
        unsafe_allow_html=True,
    )

    if st.button("⟲  Rebuild index", use_container_width=True):
        with st.spinner("Re-ingesting…"):
            try:
                stats = pipeline.ingest_documents(rebuild=True)
                st.success(f"Indexed {stats['chunks_indexed']} chunks from {stats['documents_loaded']} doc(s).")
            except Exception as exc:
                st.error(f"Rebuild failed: {exc}")

    # Personas
    st.markdown('<span class="psa-section-label">Personas</span>', unsafe_allow_html=True)
    st.markdown(
        f'''<div class="psa-persona-card">
            {persona_badge_html("Technical Expert")}
            <div class="psa-persona-desc">APIs, error codes, stack traces</div>
        </div>
        <div class="psa-persona-card">
            {persona_badge_html("Frustrated User")}
            <div class="psa-persona-desc">Urgency, repeated failures, complaints</div>
        </div>
        <div class="psa-persona-card">
            {persona_badge_html("Business Executive")}
            <div class="psa-persona-desc">Business impact, timelines, outcomes</div>
        </div>''',
        unsafe_allow_html=True,
    )

    # Analytics
    st.markdown('<span class="psa-section-label">Analytics</span>', unsafe_allow_html=True)
    st.markdown(
        '<div class="psa-analytics-link">📊 Full view in Analytics tab</div>',
        unsafe_allow_html=True,
    )
    with st.expander("Quick stats", expanded=False):
        render_analytics(in_expander=True)

    # Escalation rules
    st.markdown('<span class="psa-section-label">Escalation Rules</span>', unsafe_allow_html=True)
    st.markdown(
        f'''<ul class="psa-rule-list">
          <li>Confidence below {config.RETRIEVAL_CONFIDENCE_THRESHOLD}</li>
          <li>No documents retrieved</li>
          <li>Sensitive topic (billing, legal, GDPR)</li>
          <li>{config.MAX_USER_DISSATISFACTION_TURNS}+ consecutive frustrated turns</li>
        </ul>''',
        unsafe_allow_html=True,
    )

    st.markdown('<hr class="psa-hr">', unsafe_allow_html=True)

    if st.button("Reset conversation", use_container_width=True):
        for key in ("messages", "last_insight", "pending_prompt",
                    "pending_attachment", "pending_attachment_name"):
            st.session_state[key] = [] if key == "messages" else None
        st.session_state.consecutive_frustrated = 0
        st.session_state.pending_response       = False
        st.session_state.persona_counts         = {p: 0 for p in config.PERSONAS}
        st.session_state.escalation_count       = 0
        st.session_state.total_turns            = 0
        st.rerun()


# ── MAIN: chat | insights ──────────────────────────────────────────────────────
tab_chat, tab_analytics = st.tabs(["💬  Conversation", "📊  Analytics"])

with tab_chat:
    chat_col, insights_col = st.columns([2.3, 1.4], gap="small")
    with chat_col:
        chat_wrapper = st.container()

        with chat_wrapper:
            render_chat_area()
    with insights_col:
        render_insights_panel()

with tab_analytics:
    st.markdown(
        '<div class="psa-insights-header" style="margin-bottom:1rem;">Session Analytics</div>',
        unsafe_allow_html=True,
    )
    render_analytics(in_expander=False)