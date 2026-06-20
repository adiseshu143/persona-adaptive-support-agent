"""
rag_pipeline.py
---------------
Document ingestion, chunking, embedding, vector storage, and retrieval.

Pipeline:
  1. Load every file under data/ (.txt, .md, .pdf)
  2. Split each into overlapping chunks with metadata
  3. Embed each chunk with Gemini text-embedding-001 (BATCHED, not one-by-one)
  4. Store in persistent ChromaDB
  5. At query time: cosine-similarity top-k + keyword re-ranking

Reliability notes:
  • Embeddings are batched in groups of config.EMBEDDING_BATCH_SIZE during
    ingestion, instead of one Gemini call per chunk. For 82 chunks at batch
    size 16, this is ~6 calls instead of 82.
  • If Gemini becomes unavailable mid-ingestion (quota exhausted), the whole
    run falls back to pseudo-embeddings rather than mixing real + pseudo
    vectors in the same collection (which would corrupt similarity search).
  • retrieve_context() never raises — if the query-time embedding call fails,
    it returns no context instead of crashing the chat turn.
"""

import os
import glob

import chromadb
from pypdf import PdfReader
from langchain_text_splitters import RecursiveCharacterTextSplitter

from src import config

try:
    from google import genai
except ImportError:
    genai = None

from src.gemini_utils import get_client, gemini_retry, quota_state, note_failure_if_quota


class RAGPipeline:
    def __init__(self, db_dir: str = config.CHROMA_DIR, data_dir: str = config.DATA_DIR):
        self.data_dir      = data_dir
        self.chroma_client = chromadb.PersistentClient(path=db_dir)
        self.collection    = self.chroma_client.get_or_create_collection(
            name=config.COLLECTION_NAME
        )
        self._use_gemini = bool(config.GEMINI_API_KEY and genai is not None)

    # ── Embeddings ────────────────────────────────────────────────────────────
    @gemini_retry
    def _embed_batch_gemini(self, texts: list) -> list:
        client = get_client()
        resp = client.models.embed_content(
            model=config.EMBEDDING_MODEL,
            contents=texts,   # batched: one request, many chunks
        )
        return [list(e.values) for e in resp.embeddings]

    def get_embedding(self, text: str) -> list:
        """Single-text embedding (used at query time)."""
        if self._use_gemini and not quota_state.in_cooldown():
            try:
                return self._embed_batch_gemini([text])[0]
            except Exception as exc:
                note_failure_if_quota(exc)
                raise
        if self._use_gemini:
            # In cooldown — don't even attempt the call, fail fast so the
            # caller (retrieve_context) can degrade gracefully.
            raise RuntimeError("Gemini embeddings in cooldown after recent quota exhaustion.")
        return self._pseudo_embedding(text)

    def get_embeddings_batch(self, texts: list) -> list:
        """Batched embedding for ingestion. Falls back to pseudo-embeddings
        for ALL texts if Gemini is unavailable, to keep the vector space
        internally consistent (never mixes real + pseudo vectors)."""
        if not self._use_gemini:
            return [self._pseudo_embedding(t) for t in texts]

        out = []
        batch_size = config.EMBEDDING_BATCH_SIZE
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            try:
                out.extend(self._embed_batch_gemini(batch))
            except Exception as exc:
                note_failure_if_quota(exc)
                # Gemini became unavailable mid-ingestion — switch the WHOLE
                # run to pseudo-embeddings rather than crash, so indexing
                # still completes (degraded, but operational and consistent).
                out = [self._pseudo_embedding(t) for t in texts]
                return out

        return out

    @staticmethod
    def _pseudo_embedding(text: str, dims: int = 64) -> list:
        import hashlib
        vec = [0.0] * dims
        for token in text.lower().split():
            h = int(hashlib.md5(token.encode()).hexdigest(), 16)
            vec[h % dims] += 1.0
        norm = sum(v * v for v in vec) ** 0.5 or 1.0
        return [v / norm for v in vec]

    # ── Document loading ──────────────────────────────────────────────────────
    def load_documents(self) -> list:
        docs = []
        for path in sorted(glob.glob(os.path.join(self.data_dir, "*"))):
            fname = os.path.basename(path)
            ext   = fname.lower().rsplit(".", 1)[-1]

            if ext in ("txt", "md"):
                with open(path, "r", encoding="utf-8") as f:
                    docs.append({"source": fname, "page": None, "text": f.read()})

            elif ext == "pdf":
                reader = PdfReader(path)
                for i, page in enumerate(reader.pages, start=1):
                    text = page.extract_text() or ""
                    if text.strip():
                        docs.append({"source": fname, "page": i, "text": text})

        return docs

    # ── Chunking ──────────────────────────────────────────────────────────────
    def chunk_documents(self, documents: list) -> list:
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=config.CHUNK_SIZE,
            chunk_overlap=config.CHUNK_OVERLAP,
            separators=["\n\n", "\n", " ", ""],
        )
        chunks = []
        for doc in documents:
            for idx, text in enumerate(splitter.split_text(doc["text"])):
                chunks.append({
                    "text":        text,
                    "source":      doc["source"],
                    "page":        doc["page"],
                    "chunk_index": idx,
                })
        return chunks

    # ── Ingestion ─────────────────────────────────────────────────────────────
    def ingest_documents(self, rebuild: bool = True) -> dict:
        if rebuild:
            try:
                self.chroma_client.delete_collection(config.COLLECTION_NAME)
            except Exception:
                pass
            self.collection = self.chroma_client.get_or_create_collection(
                name=config.COLLECTION_NAME
            )

        documents = self.load_documents()
        chunks    = self.chunk_documents(documents)

        texts = [c["text"] for c in chunks]
        embeddings = self.get_embeddings_batch(texts)   # batched, not per-chunk

        ids, metadatas = [], []
        for i, chunk in enumerate(chunks):
            cid = f"{chunk['source']}_p{chunk['page']}_c{chunk['chunk_index']}_{i}"
            ids.append(cid)
            metadatas.append({
                "source":      chunk["source"],
                "page":        chunk["page"] if chunk["page"] is not None else -1,
                "chunk_index": chunk["chunk_index"],
            })

        if ids:
            self.collection.add(
                ids=ids, embeddings=embeddings, metadatas=metadatas, documents=texts
            )

        return {
            "documents_loaded": len(documents),
            "chunks_indexed":   len(chunks),
            "files_found":      len(documents),
        }

    # ── Retrieval ─────────────────────────────────────────────────────────────
    @staticmethod
    def _keyword_boost(query: str, chunks: list) -> list:
        q_tokens = {t for t in query.lower().split() if len(t) > 2}
        if not q_tokens:
            return chunks
        for chunk in chunks:
            overlap = len(q_tokens & set(chunk["text"].lower().split()))
            chunk["score"] = round(min(1.0, chunk["score"] + min(0.15, 0.03 * overlap)), 4)
        return sorted(chunks, key=lambda c: c["score"], reverse=True)

    def retrieve_context(self, query: str, top_k: int = config.TOP_K) -> list:
        if self.collection.count() == 0:
            return []

        try:
            fetch_k      = min(top_k * 2, self.collection.count())
            query_vector = self.get_embedding(query)
        except Exception:
            # Embedding quota exhausted (or in cooldown) mid-conversation —
            # degrade gracefully to "no KB match" instead of crashing the turn.
            return []

        results = self.collection.query(
            query_embeddings=[query_vector], n_results=fetch_k
        )

        retrieved = []
        if results and results.get("documents") and results["documents"][0]:
            for i in range(len(results["documents"][0])):
                distance = (results.get("distances") or [[1.0] * fetch_k])[0][i]
                score    = max(0.0, 1.0 - (distance / 2.0))
                meta     = results["metadatas"][0][i]
                retrieved.append({
                    "text":   results["documents"][0][i],
                    "source": meta.get("source"),
                    "page":   meta.get("page") if meta.get("page", -1) != -1 else None,
                    "score":  round(score, 4),
                })

        ranked = self._keyword_boost(query, retrieved)
        return ranked[:top_k]