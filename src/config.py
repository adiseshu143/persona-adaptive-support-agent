"""
config.py
----------
Central configuration for the Persona-Adaptive Customer Support Agent.

Every tunable constant the rest of the app depends on lives here so that
behaviour (chunking, thresholds, model names, escalation keywords) can be
changed in one place without touching pipeline logic.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# API / Model configuration
# ---------------------------------------------------------------------------
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

CLASSIFIER_MODEL = "gemini-2.5-flash"
GENERATOR_MODEL = "gemini-2.5-flash"
EMBEDDING_MODEL = "gemini-embedding-001"

# ---------------------------------------------------------------------------
# RAG pipeline configuration
# ---------------------------------------------------------------------------
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
CHROMA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "chroma_db")
COLLECTION_NAME = "support_kb"

CHUNK_SIZE = 500
CHUNK_OVERLAP = 50
TOP_K = 3

# ---------------------------------------------------------------------------
# Escalation configuration
# ---------------------------------------------------------------------------
RETRIEVAL_CONFIDENCE_THRESHOLD = 0.45

# Keywords that automatically flag a query as sensitive, regardless of
# retrieval confidence. Matched case-insensitively against the raw message.
SENSITIVE_TOPIC_KEYWORDS = [
    "refund", "chargeback", "duplicate charge", "billing dispute",
    "cancel my subscription", "legal", "lawsuit", "gdpr", "data deletion",
    "account ownership", "transfer ownership", "fraud", "unauthorized charge",
    "delete my account", "compliance", "subpoena", "contract terms",
]

# How many consecutive turns of unresolved frustration before we escalate
# even if retrieval confidence looks fine.
MAX_USER_DISSATISFACTION_TURNS = 2

# ---------------------------------------------------------------------------
# Persona configuration
# ---------------------------------------------------------------------------
PERSONAS = ["Technical Expert", "Frustrated User", "Business Executive"]

PERSONA_BADGE_COLOR = {
    "Technical Expert": "#3D5A80",
    "Frustrated User": "#B5482A",
    "Business Executive": "#7A6A2E",
}

PERSONA_ICON = {
    "Technical Expert": "</>",
    "Frustrated User": "!",
    "Business Executive": "$",
}