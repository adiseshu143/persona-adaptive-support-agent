"""
app.py
------
Streamlit front-end for the Persona-Adaptive Customer Support Agent.

Run with:  streamlit run app.py
"""

import os
import sys
import json
from datetime import datetime
import time
import streamlit as st
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src import config, classifier, generator, escalator
from src.classifier import is_chitchat
from src.rag_pipeline import RAGPipeline


# ---------------------------------------------------------------------------
# Page setup
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Persona-Adaptive Support Agent",
    page_icon="🗂️",
    layout="wide",
    initial_sidebar_state="expanded"
)

CSS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "style.css")
with open(CSS_PATH, "r", encoding="utf-8") as f:
    st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Resources & session state
# ---------------------------------------------------------------------------
@st.cache_resource(show_spinner=False)
def get_pipeline():
    pipeline = RAGPipeline()
    ingest_result = None
    ingest_error = None
    if pipeline.collection.count() == 0:
        try:
            ingest_result = pipeline.ingest_documents()
        except Exception as exc:  # noqa: BLE001
            ingest_error = str(exc)
    return pipeline, ingest_result, ingest_error


def init_state():
    defaults = {
        "messages": [],
        "consecutive_frustrated": 0,
        "last_insight": None,
        "persona_counts": {p: 0 for p in config.PERSONAS},
        "escalation_count": 0,
        "total_turns": 0,
        "pending_response": False,
        "pending_prompt": None,
        "pending_attachment": None,
        "pending_attachment_name": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


init_state()
pipeline, ingest_result, ingest_error = get_pipeline()


# ---------------------------------------------------------------------------
# Small render helpers
# ---------------------------------------------------------------------------
_BADGE_CLASS = {
    "Technical Expert": "badge-tech",
    "Frustrated User": "badge-frustrated",
    "Business Executive": "badge-executive",
}
_METER_COLOR = {
    "Technical Expert": "var(--tech)",
    "Frustrated User": "var(--frustrated)",
    "Business Executive": "var(--executive)",
}


def persona_badge_html(persona: str) -> str:
    css_class = _BADGE_CLASS.get(persona, "badge-tech")
    icon = config.PERSONA_ICON.get(persona, "")
    return f'<span class="psa-badge {css_class}">{icon} {persona}</span>'


def confidence_meter_html(score: float, color: str) -> str:
    pct = max(0, min(100, round(score * 100)))
    return (
        '<div class="psa-meter-row">'
        f'<div class="psa-meter-track"><div class="psa-meter-fill" '
        f'style="width:{pct}%; background:{color};"></div></div>'
        f'<div class="psa-meter-label">{pct}%</div>'
        '</div>'
    )


def source_chip_html(chunk: dict) -> str:
    page_label = f" · p.{chunk['page']}" if chunk.get("page") else ""
    snippet = chunk["text"].strip().replace("\n", " ")
    if len(snippet) > 160:
        snippet = snippet[:160] + "..."
    return (
        '<div class="psa-source">'
        f'<div class="fname">{chunk["source"]}{page_label} — confidence {chunk["score"]:.2f}</div>'
        f'<div class="snippet">{snippet}</div>'
        '</div>'
    )


def render_messages(container, messages, show_typing=False):
    """Render all messages and optionally a typing indicator as the last item."""
    with container:
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


# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
st.markdown(
    f'''
    <div class="psa-header">
        <div class="brandblock">
            <span class="psa-title">Persona-Adaptive Support Desk</span>
            <span class="psa-eyebrow">CHATBOT</span>
        </div>
        <div class="meta">Knowledge base: {pipeline.collection.count()} chunks indexed<br/>
        {datetime.now().strftime("%d %b %Y, %H:%M")}</div>
    </div>
    ''',
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown(
        '''
        <div class="psa-brand">
            <div class="psa-brand-name">Support Desk</div>
            <div class="psa-brand-sub">AI Customer Support</div>
        </div>
        ''',
        unsafe_allow_html=True
    )

    st.markdown('<div class="psa-section-label">Knowledge Base</div>', unsafe_allow_html=True)

    if ingest_error:
        st.markdown(
            f'<div class="psa-alert psa-alert-error">'
            f'<strong>Ingestion failed</strong><br/>{ingest_error}</div>',
            unsafe_allow_html=True,
        )
    elif ingest_result and ingest_result.get("files_found", 0) > 0 and ingest_result.get("chunks_indexed", 0) == 0:
        st.markdown(
            f'<div class="psa-alert psa-alert-warning">'
            f'<strong>0 chunks indexed</strong><br/>'
            f'{ingest_result["files_found"]} file(s) found in /data but nothing was '
            f'indexed. Check the Debug panel below.</div>',
            unsafe_allow_html=True,
        )

    chunk_count = pipeline.collection.count()
    st.markdown(
        f'''
        <div class="psa-stat-row">
          <div class="psa-stat-tile">
            <div class="psa-stat-value">{chunk_count}</div>
            <div class="psa-stat-label">Chunks indexed</div>
          </div>
        </div>
        ''',
        unsafe_allow_html=True,
    )

    if st.button("⟲  Rebuild index", use_container_width=True):
        with st.spinner("Re-ingesting documents..."):
            try:
                stats = pipeline.ingest_documents(rebuild=True)
                st.success(f"Indexed {stats['chunks_indexed']} chunks from {stats['documents_loaded']} document(s).")
            except Exception as exc:  # noqa: BLE001
                st.error(f"Rebuild failed: {exc}")

    st.markdown('<div style="height:8px"></div>', unsafe_allow_html=True)
    st.markdown('<div class="psa-section-label">Personas</div>', unsafe_allow_html=True)
    st.markdown(
        f'''
        <div class="psa-persona-row">
            {persona_badge_html("Technical Expert")}
            <span class="psa-persona-desc">Technical jargon, APIs, error codes</span>
        </div>

        <div class="psa-persona-row">
            {persona_badge_html("Frustrated User")}
            <span class="psa-persona-desc">Urgency, complaints, repeated failures</span>
        </div>

        <div class="psa-persona-row">
            {persona_badge_html("Business Executive")}
            <span class="psa-persona-desc">Business impact, timelines, outcomes</span>
        </div>
        ''',
        unsafe_allow_html=True,
    )

    st.markdown('<div style="height:8px"></div>', unsafe_allow_html=True)
    st.markdown('<div class="psa-section-label">Escalation rules</div>', unsafe_allow_html=True)
    st.markdown(
        f'''
        <ul class="psa-rule-list">
          <li>Confidence below {config.RETRIEVAL_CONFIDENCE_THRESHOLD}</li>
          <li>No documents retrieved</li>
          <li>Sensitive topic (billing, legal, account changes)</li>
          <li>{config.MAX_USER_DISSATISFACTION_TURNS}+ consecutive frustrated turns</li>
        </ul>
        ''',
        unsafe_allow_html=True,
    )

    st.markdown('<hr class="psa-hr"/>', unsafe_allow_html=True)
    if st.button("Reset conversation", use_container_width=True):
        st.session_state.messages = []
        st.session_state.consecutive_frustrated = 0
        st.session_state.last_insight = None
        st.session_state.pending_response = False
        st.session_state.pending_prompt = None
        st.session_state.pending_attachment = None
        st.session_state.pending_attachment_name = None
        st.rerun()


# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------
tab_chat, tab_analytics = st.tabs(["Conversation", "Analytics"])

with tab_chat:
    col_chat, col_insights = st.columns([2.4, 1], gap="medium")

    with col_chat:
        # ── Chat container ──────────────────────────────────────────────────
        chat_container = st.container(height=350)

        # Phase 1: user just submitted → show messages + typing indicator,
        #           then generate the response and rerun to show it cleanly.
        if st.session_state.pending_response:
            prompt        = st.session_state.pending_prompt
            attachment    = st.session_state.pending_attachment
            attachment_name = st.session_state.pending_attachment_name

            # Render history + typing indicator
            render_messages(chat_container, st.session_state.messages, show_typing=True)

            # ── Generate ────────────────────────────────────────────────────
            chitchat = is_chitchat(prompt) and attachment is None

            if chitchat:
                response_text = generator.generate_casual_reply(prompt)
                escalation_check = {"escalate": False, "reasons": [], "best_score": 0.0}
                context_chunks = []
                handoff = None
                persona_result = None
            else:
                persona_result = classifier.classify_persona(prompt)
                persona = persona_result["persona"]

                if persona == "Frustrated User":
                    st.session_state.consecutive_frustrated += 1
                else:
                    st.session_state.consecutive_frustrated = 0

                context_chunks = pipeline.retrieve_context(prompt)
                escalation_check = escalator.check_escalation(
                    user_query=prompt,
                    persona=persona,
                    context_chunks=context_chunks,
                    consecutive_frustrated_turns=st.session_state.consecutive_frustrated,
                )

                handoff = None
                if escalation_check["escalate"]:
                    handoff = escalator.build_handoff_summary(
                        user_query=prompt,
                        persona=persona,
                        context_chunks=context_chunks,
                        conversation_history=st.session_state.messages,
                        escalation_check=escalation_check,
                    )
                    response_text = (
                        "I don't want to guess on this one and risk giving you the wrong "
                        "answer, so I'm bringing in a specialist who can dig in properly. "
                        "I've put together a quick summary of what we've covered so you "
                        "won't have to explain everything again."
                    )
                else:
                    response_text = generator.generate_response(
                        prompt,
                        persona,
                        context_chunks,
                        attachment,
                    )

            # ── Commit response to state ────────────────────────────────────
            st.session_state.messages.append({"role": "assistant", "content": response_text})

            if not chitchat:
                st.session_state.persona_counts[persona] = \
                    st.session_state.persona_counts.get(persona, 0) + 1
                st.session_state.total_turns += 1
                if escalation_check["escalate"]:
                    st.session_state.escalation_count += 1

                st.session_state.last_insight = {
                    "persona": persona,
                    "confidence": persona_result["confidence"],
                    "reasoning": persona_result.get("reasoning", ""),
                    "context_chunks": context_chunks,
                    "escalation_check": escalation_check,
                    "handoff": handoff,
                }
            else:
                st.session_state.last_insight = {"casual": True}

            # Clear pending state and rerun to render the final message
            st.session_state.pending_response = False
            st.session_state.pending_prompt = None
            st.session_state.pending_attachment = None
            st.session_state.pending_attachment_name = None
            st.rerun()

        else:
            # Normal render — no pending response
            render_messages(chat_container, st.session_state.messages, show_typing=False)

        # ── Input bar ───────────────────────────────────────────────────────
        st.markdown('<div class="chat-bar">', unsafe_allow_html=True)

        col1, col2 = st.columns([1.8, 12], vertical_alignment="center")

        with col1:
            with st.popover("➕"):
                uploaded_file = st.file_uploader(
                    "Upload File",
                    label_visibility="collapsed",
                    key=f"uploader_{st.session_state.get('uploader_key', 0)}",
                )

        with col2:
            prompt = st.chat_input("Type a message...")

        st.markdown('</div>', unsafe_allow_html=True)

        # ── Handle new submission ────────────────────────────────────────────
        if prompt:
            attachment = None
            attachment_name = None
            if uploaded_file is not None:
                attachment = {
                    "bytes": uploaded_file.getvalue(),
                    "mime_type": uploaded_file.type or "application/octet-stream",
                }
                attachment_name = uploaded_file.name
                st.session_state["uploader_key"] = st.session_state.get("uploader_key", 0) + 1

            # Append user message immediately
            st.session_state.messages.append({
                "role": "user",
                "content": prompt,
                "attachment_name": attachment_name,
            })

            # Store pending work for next rerun
            st.session_state.pending_response = True
            st.session_state.pending_prompt = prompt
            st.session_state.pending_attachment = attachment
            st.session_state.pending_attachment_name = attachment_name

            st.rerun()

    # ── Insights panel ───────────────────────────────────────────────────────
    with col_insights:
        st.markdown('<div class="psa-section-label">Case Insights</div>', unsafe_allow_html=True)

        insight = st.session_state.last_insight
        if insight is None:
            st.markdown(
                '<div class="psa-card"><span style="color:var(--text-muted); font-size:0.85rem;">'
                'Send a message to see persona detection, retrieval, and escalation status here.'
                '</span></div>',
                unsafe_allow_html=True,
            )
        elif insight.get("casual"):
            st.markdown(
                '<div class="psa-card"><span style="color:var(--text-muted); font-size:0.85rem;">'
                'Just a casual message — nothing to classify or look up here. '
                'Ask a support question to see the full breakdown.'
                '</span></div>',
                unsafe_allow_html=True,
            )
        else:
            persona = insight["persona"]
            st.markdown(
                f'<div class="psa-card">'
                f'<div class="psa-card-title">Detected persona</div>'
                f'{persona_badge_html(persona)}'
                f'{confidence_meter_html(insight["confidence"], _METER_COLOR.get(persona, "var(--tech)"))}'
                f'<div style="font-size:0.78rem; color:var(--text-muted); margin-top:0.3rem;">{insight["reasoning"]}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

            sources_html = "".join(source_chip_html(c) for c in insight["context_chunks"]) or (
                '<div style="font-size:0.82rem; color:var(--text-muted);">No matching documents retrieved.</div>'
            )
            st.markdown(
                f'<div class="psa-card"><div class="psa-card-title">Retrieved sources</div>{sources_html}</div>',
                unsafe_allow_html=True,
            )

            seen_sources = []
            for c in insight["context_chunks"]:
                if c["source"] in seen_sources:
                    continue
                seen_sources.append(c["source"])
                file_path = os.path.join(config.DATA_DIR, c["source"])
                if os.path.isfile(file_path):
                    with open(file_path, "rb") as fh:
                        st.download_button(
                            label=f"⬇ {c['source']}",
                            data=fh.read(),
                            file_name=c["source"],
                            key=f"dl_{c['source']}_{len(st.session_state.messages)}",
                            use_container_width=True,
                        )

            escalation_check = insight["escalation_check"]
            status_class = "status-escalated" if escalation_check["escalate"] else "status-ok"
            status_label = "ESCALATED" if escalation_check["escalate"] else "RESOLVED · NO ESCALATION"
            reasons_html = "".join(f"<li>{r}</li>" for r in escalation_check["reasons"])
            st.markdown(
                f'<div class="psa-card">'
                f'<div class="psa-card-title">Escalation status</div>'
                f'<span class="psa-status {status_class}">{status_label}</span>'
                f'{f"<ul style=font-size:0.8rem;color:var(--text-muted);margin-top:0.5rem;>{reasons_html}</ul>" if reasons_html else ""}'
                f'</div>',
                unsafe_allow_html=True,
            )

            if insight["handoff"]:
                st.markdown('<div class="psa-card"><div class="psa-card-title">Human handoff summary</div></div>', unsafe_allow_html=True)
                st.code(json.dumps(insight["handoff"], indent=2), language="json")

with tab_analytics:
    st.markdown('<div class="psa-section-label">Session Analytics</div>', unsafe_allow_html=True)

    m1, m2, m3 = st.columns(3)
    with m1:
        st.metric("Total turns", st.session_state.total_turns)
    with m2:
        st.metric("Escalations", st.session_state.escalation_count)
    with m3:
        rate = (
            round(100 * st.session_state.escalation_count / st.session_state.total_turns)
            if st.session_state.total_turns else 0
        )
        st.metric("Escalation rate", f"{rate}%")

    st.markdown('<div style="height:0.6rem;"></div>', unsafe_allow_html=True)
    df = pd.DataFrame({
        "Persona": list(st.session_state.persona_counts.keys()),
        "Messages": list(st.session_state.persona_counts.values()),
    }).set_index("Persona")
    st.markdown('<div class="psa-card"><div class="psa-card-title">Persona distribution</div></div>', unsafe_allow_html=True)
    st.bar_chart(df, color="#14213D")