"""
config.py
---------
Central configuration. All tunables in one place.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ── API / Models ──────────────────────────────────────────────────────────────
GEMINI_API_KEY   = os.environ.get("GEMINI_API_KEY", "")
CLASSIFIER_MODEL = "gemini-2.5-flash"
GENERATOR_MODEL  = "gemini-2.5-flash"
EMBEDDING_MODEL  = "gemini-embedding-001"

# ── RAG ───────────────────────────────────────────────────────────────────────
_ROOT            = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR         = os.path.join(_ROOT, "data")
CHROMA_DIR       = os.path.join(_ROOT, "chroma_db")
COLLECTION_NAME  = "support_kb"
CHUNK_SIZE       = 500
CHUNK_OVERLAP    = 50
TOP_K            = 3

# ── Escalation ────────────────────────────────────────────────────────────────
RETRIEVAL_CONFIDENCE_THRESHOLD = 0.45

SENSITIVE_TOPIC_KEYWORDS = [
    "refund", "chargeback", "duplicate charge", "billing dispute",
    "cancel my subscription", "legal", "lawsuit", "gdpr", "data deletion",
    "account ownership", "transfer ownership", "fraud", "unauthorized charge",
    "delete my account", "compliance", "subpoena", "contract terms",
]

MAX_USER_DISSATISFACTION_TURNS = 2

# ── Personas ──────────────────────────────────────────────────────────────────
PERSONAS = ["Technical Expert", "Frustrated User", "Business Executive"]

PERSONA_ICON = {
    "Technical Expert":  "</>",
    "Frustrated User":   "!",
    "Business Executive":"$",
}

# ── Gemini reliability tuning ──────────────────────────────────────────────────
GEMINI_MAX_RETRIES        = 2     # small, bounded — don't hammer an exhausted quota
GEMINI_RETRY_BASE_SECONDS = 1.5   # exponential backoff base
GEMINI_COOLDOWN_SECONDS   = 45    # after a 429, skip Gemini entirely for this long
EMBEDDING_BATCH_SIZE      = 16    # chunks embedded per API call during ingestion