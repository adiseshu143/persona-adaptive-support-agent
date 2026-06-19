# Persona-Adaptive Customer Support Agent

An AI support agent that detects who it's talking to, answers strictly from
a grounded knowledge base, adapts its tone to the customer, and hands off
to a human the moment automation isn't safe enough.

---

## 1. Project Overview

Most support bots have the same flaw: one tone for everyone, hallucinated
answers when documentation is thin, and no clean way to bring in a human
when they're stuck. This project addresses all three by combining:

- **Persona detection** — classifies every incoming message as a
  *Technical Expert*, *Frustrated User*, or *Business Executive*.
- **Retrieval-Augmented Generation (RAG)** — answers are generated only
  from chunks retrieved from a local knowledge base, never from the
  model's own assumptions.
- **Escalation logic** — low retrieval confidence, sensitive topics
  (billing, legal, account changes), or repeated unresolved frustration
  all trigger a structured handoff to a human agent instead of a guess.

The whole pipeline runs through a single Streamlit app.

---

## 2. Tech Stack

| Layer | Choice | Version |
|---|---|---|
| Language | Python | 3.11+ |
| UI | Streamlit | >=1.30.0 |
| LLM (classification + generation) | Google Gemini (`gemini-2.5-flash-preview-09-2025`) | google-genai >=0.1.0 |
| Embeddings | Gemini `text-embedding-004` | — |
| Vector DB | ChromaDB (persistent local store) | >=0.4.0 |
| Document parsing | pypdf | >=3.0.0 |
| Chunking | langchain-text-splitters (`RecursiveCharacterTextSplitter`) | >=0.2.0 |
| Secrets | python-dotenv | >=1.0.0 |
| Analytics | pandas | >=2.0.0 |

---

## 3. Architecture

```
User Message
     │
     ▼
Persona Classifier ───► Persona Tag: Technical Expert / Frustrated User / Business Executive
     │
     ▼
Vector Database (ChromaDB) ───► Cosine Similarity Search ───► Top-K Chunks
     │
     ▼
Retrieval Quality Check
     │
     ├── Sufficient confidence, no sensitive topic ──► Adaptive Generator ──► Response shown to user
     │
     └── Low confidence / sensitive topic / repeated frustration
                  │
                  ▼
          Escalator ──► Structured Handoff JSON ──► Human Agent
```

Each stage is its own module so it can be tested, swapped, or tuned in
isolation:

```
persona-support-agent/
├── data/                       # knowledge base (.txt, .md, .pdf)
├── src/
│   ├── config.py               # thresholds, model names, keyword lists
│   ├── classifier.py           # persona detection
│   ├── rag_pipeline.py         # ingestion, chunking, embeddings, retrieval
│   ├── generator.py            # persona-aware prompt building + generation
│   └── escalator.py            # escalation rules + handoff JSON builder
├── app.py                      # Streamlit UI
├── style.css                   # custom visual theme
├── requirements.txt
├── .env.example
└── README.md
```

---

## 4. Persona Detection Strategy

**Method:** structured JSON classification via Gemini's
`response_schema`, constrained to an enum of the three required personas,
returning `persona`, `confidence`, and `reasoning`.

**Prompt design:** the system instruction explicitly defines each
persona's lexical signature (jargon/APIs for Technical Expert, emotional
urgency for Frustrated User, ROI/timeline language for Business
Executive) so the model isn't guessing at the taxonomy.

**Reliability fallback:** if the Gemini call fails for any reason (missing
key, rate limit, malformed response), `classifier.py` falls back to a
deterministic keyword + heuristic scorer (jargon terms, exclamation
density, ALL-CAPS detection, business-impact vocabulary). This means the
app is still demoable without a live API key and never crashes the
pipeline if classification fails mid-conversation.

---

## 5. RAG Pipeline Design

- **Chunking:** `RecursiveCharacterTextSplitter`, chunk size **500**
  characters, overlap **50** characters, splitting on paragraph → sentence
  → word → character boundaries in that order, so policy steps and error
  codes aren't sliced apart.
- **Embeddings:** Gemini `text-embedding-004`. (If no API key is present,
  a deterministic hash-based pseudo-embedding is used instead purely so
  the retrieval mechanics remain testable offline — it is **not**
  semantically meaningful and should not be relied on for real answers.)
- **Vector database:** ChromaDB with a **persistent** local store at
  `./chroma_db`, so the index survives restarts and isn't rebuilt on every
  session.
- **Retrieval:** top-**k = 3** chunks per query, each returned with
  source filename, page number (for PDFs), and a normalized 0–1
  confidence score derived from vector distance.
- **Metadata:** every chunk stores `source`, `page` (or `null` for
  non-PDFs), and `chunk_index`, so retrieved answers can always be traced
  back to a specific document.

---

## 6. Escalation Logic

Escalation triggers, all configurable in `src/config.py`:

| Trigger | Config value |
|---|---|
| No documents retrieved | — |
| Top retrieval confidence below threshold | `RETRIEVAL_CONFIDENCE_THRESHOLD = 0.45` |
| Sensitive-topic keyword match | `SENSITIVE_TOPIC_KEYWORDS` (billing disputes, refunds, legal, account ownership, etc.) |
| Repeated unresolved frustration | `MAX_USER_DISSATISFACTION_TURNS = 2` consecutive turns |

When any trigger fires, `escalator.build_handoff_summary()` produces a
structured JSON package containing: detected persona, a trimmed issue
summary, full conversation history, every retrieved source with its
score, attempted steps, the specific escalation reason(s), and a
persona-aware recommendation for the human agent — so the case can be
picked up without re-reading the whole thread.

---

## 7. Setup Instructions

```bash
# 1. Clone and enter the project
git clone <your-repo-url>
cd persona-support-agent

# 2. Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure your API key
cp .env.example .env
# then edit .env and paste your real Gemini API key

# 5. Run the app
streamlit run app.py
```

The first run automatically ingests every file in `/data` into ChromaDB.
Use the **"Rebuild index"** button in the sidebar any time you add or
edit knowledge base documents.

---

## 8. Environment Variables

| Variable | Required | Description |
|---|---|---|
| `GEMINI_API_KEY` | Yes (for live LLM calls) | Your Google Gemini API key. Without it, the app still runs using the offline keyword-classifier and raw-context fallbacks described above, for structural testing/demo purposes. |

---

## 9. Example Queries

| # | Message | Expected Persona | Expected Behavior |
|---|---|---|---|
| 1 | "What are the header parameter requirements for your bearer token auth implementation?" | Technical Expert | Detailed, code-level answer grounded in `api_authentication_troubleshooting.md` |
| 2 | "It's been an hour and nothing is loading, this is so frustrating!" | Frustrated User | Empathetic opener, simple bulleted steps from `browser_cache_and_cookies.md` |
| 3 | "How does this outage impact our operations and when will it be resolved?" | Business Executive | Concise, impact-first answer referencing `service_outage_response_policy.md` |
| 4 | "My billing statement has duplicate charges, I demand a refund!" | Frustrated User | **Escalates** — sensitive billing topic, handoff JSON generated |
| 5 | "We need to update account ownership and contract terms." | Business Executive | **Escalates** — account-sensitive/legal topic |

---

## 10. Conversational Behavior

A few deliberate design choices worth knowing about:

- **Casual messages bypass the support pipeline.** Greetings, thanks, and
  small talk ("hi", "thanks", "how are you") are detected by
  `classifier.is_chitchat()` and answered directly and warmly, with no
  persona forced, no document retrieval, and no escalation check. Forcing a
  bare "hi" through the full pipeline is what caused odd misclassifications
  and unnecessary escalation in earlier versions — chitchat simply isn't a
  support query.
- **Responses never narrate the classification.** The system prompts
  explicitly forbid phrases like "as a frustrated user" or "based on your
  business impact concerns" — the tone adapts, but the model never tells the
  customer how it categorized them. Persona/confidence/reasoning are only
  surfaced in the **Case Insights** panel for transparency, never in the chat
  itself.
- **Attachments.** Customers can attach a screenshot, PDF, or text file via
  the uploader above the chat box. The file is sent to Gemini alongside the
  question (multimodal `generate_content` call), so the model can actually
  look at an error screenshot or document and respond accordingly.
- **Source downloads.** Each retrieved source in the Case Insights panel has
  a download button so the customer (or a reviewer) can grab the original
  KB document — including the PDF — directly from the chat.

## 11. Known Limitations

- Persona classification on very short or ambiguous one-line messages can
  be uncertain; the confidence score is shown transparently so this is
  visible rather than hidden.
- Retrieval quality depends on chunk size/overlap tuning and will need
  revisiting if the knowledge base grows significantly beyond the current
  ~13 documents.
- The offline fallback embeddings (used only when no API key is set) are
  not semantically meaningful — they exist purely to keep the pipeline
  runnable for structural testing, not for real answer quality.
- Escalation thresholds are static per-session; there's no persistent
  multi-session memory of a customer's prior frustration.
- Streamlit's session state resets on browser refresh — there is no
  database-backed conversation persistence in this version.

## 12. Future Enhancements

Multi-turn sentiment tracking across sessions, LangGraph-based workflow
orchestration, a dedicated analytics dashboard with historical escalation
trends, and a human-approval step before sending responses on sensitive
topics.

treamlit run app.py`treamlit run app.py`