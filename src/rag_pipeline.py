"""
rag_pipeline.py
----------------
Document ingestion, chunking, embedding, vector storage, and retrieval.

Pipeline:
  1. Load every file under data/ (.txt, .md, .pdf)
  2. Split each into overlapping chunks with metadata (source, chunk index,
     and page number for PDFs)
  3. Embed each chunk with Gemini's text-embedding-004
  4. Store embeddings + text + metadata in a persistent ChromaDB collection
  5. At query time: embed the query, run a cosine-similarity top-k search,
     and return chunks with a normalized confidence score for the
     escalation logic to consume.
"""

import os
import glob

import chromadb
from pypdf import PdfReader
from langchain_text_splitters import RecursiveCharacterTextSplitter

from src import config

try:
    from google import genai
except ImportError:  # pragma: no cover
    genai = None


class RAGPipeline:
    def __init__(self, db_dir: str = config.CHROMA_DIR, data_dir: str = config.DATA_DIR):
        self.data_dir = data_dir
        self.chroma_client = chromadb.PersistentClient(path=db_dir)
        self.collection = self.chroma_client.get_or_create_collection(name=config.COLLECTION_NAME)
        self._genai_client = None
        if config.GEMINI_API_KEY and genai is not None:
            self._genai_client = genai.Client(api_key=config.GEMINI_API_KEY)

    # ------------------------------------------------------------------
    # Embeddings
    # ------------------------------------------------------------------
    def get_embedding(self, text: str) -> list:
        """Call Gemini's embedding model. Falls back to a deterministic
        hash-based pseudo-embedding if no API key is configured, so the
        retrieval pipeline can still be exercised offline/in tests."""
        if self._genai_client is not None:
            response = self._genai_client.models.embed_content(
                model=config.EMBEDDING_MODEL,
                contents=text,
            )
            return list(response.embeddings[0].values)
        return self._pseudo_embedding(text)

    @staticmethod
    def _pseudo_embedding(text: str, dims: int = 64) -> list:
        """Deterministic, dependency-free fallback embedding (NOT semantic).
        Only used when no Gemini API key is present, purely so the rest of
        the app remains runnable for structural testing/demo purposes."""
        import hashlib
        vec = [0.0] * dims
        for i, token in enumerate(text.lower().split()):
            h = int(hashlib.md5(token.encode()).hexdigest(), 16)
            vec[h % dims] += 1.0
        norm = sum(v * v for v in vec) ** 0.5 or 1.0
        return [v / norm for v in vec]

    # ------------------------------------------------------------------
    # Document loading
    # ------------------------------------------------------------------
    def load_documents(self) -> list:
        """Returns a list of {"source": filename, "page": int|None, "text": str}."""
        documents = []
        for path in sorted(glob.glob(os.path.join(self.data_dir, "*"))):
            filename = os.path.basename(path)
            ext = filename.lower().split(".")[-1]

            if ext in ("txt", "md"):
                with open(path, "r", encoding="utf-8") as f:
                    documents.append({"source": filename, "page": None, "text": f.read()})

            elif ext == "pdf":
                reader = PdfReader(path)
                for page_num, page in enumerate(reader.pages, start=1):
                    text = page.extract_text() or ""
                    if text.strip():
                        documents.append({"source": filename, "page": page_num, "text": text})

        return documents

    # ------------------------------------------------------------------
    # Chunking
    # ------------------------------------------------------------------
    def chunk_documents(self, documents: list) -> list:
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=config.CHUNK_SIZE,
            chunk_overlap=config.CHUNK_OVERLAP,
            separators=["\n\n", "\n", " ", ""],
        )
        chunks = []
        for doc in documents:
            for idx, chunk_text in enumerate(splitter.split_text(doc["text"])):
                chunks.append({
                    "text": chunk_text,
                    "source": doc["source"],
                    "page": doc["page"],
                    "chunk_index": idx,
                })
        return chunks

    # ------------------------------------------------------------------
    # Ingestion
    # ------------------------------------------------------------------
    def ingest_documents(self, rebuild: bool = True) -> dict:
        """Loads, chunks, embeds, and (re)indexes the entire data/ directory."""
        if rebuild:
            try:
                self.chroma_client.delete_collection(config.COLLECTION_NAME)
            except Exception:
                pass
            self.collection = self.chroma_client.get_or_create_collection(name=config.COLLECTION_NAME)

        documents = self.load_documents()
        chunks = self.chunk_documents(documents)

        ids, embeddings, metadatas, texts = [], [], [], []
        for i, chunk in enumerate(chunks):
            chunk_id = f"{chunk['source']}_p{chunk['page']}_c{chunk['chunk_index']}_{i}"
            ids.append(chunk_id)
            embeddings.append(self.get_embedding(chunk["text"]))
            metadatas.append({
                "source": chunk["source"],
                "page": chunk["page"] if chunk["page"] is not None else -1,
                "chunk_index": chunk["chunk_index"],
            })
            texts.append(chunk["text"])

        if ids:
            self.collection.add(ids=ids, embeddings=embeddings, metadatas=metadatas, documents=texts)

        return {"documents_loaded": len(documents), "chunks_indexed": len(chunks)}

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------
    def retrieve_context(self, query: str, top_k: int = config.TOP_K) -> list:
        """Returns top_k chunks as:
        [{"text", "source", "page", "score"}], score in [0, 1], higher = better.
        """
        if self.collection.count() == 0:
            return []

        query_vector = self.get_embedding(query)
        results = self.collection.query(query_embeddings=[query_vector], n_results=top_k)

        retrieved = []
        if results and results.get("documents") and results["documents"][0]:
            for i in range(len(results["documents"][0])):
                distance = results["distances"][0][i] if results.get("distances") else 1.0
                # Chroma's default space is squared-L2 on normalized vectors here,
                # so we convert distance -> a 0-1 similarity-style confidence score.
                score = max(0.0, 1.0 - (distance / 2.0))
                meta = results["metadatas"][0][i]
                retrieved.append({
                    "text": results["documents"][0][i],
                    "source": meta.get("source"),
                    "page": meta.get("page") if meta.get("page", -1) != -1 else None,
                    "score": round(score, 4),
                })
        return retrieved


if __name__ == "__main__":
    pipeline = RAGPipeline()
    stats = pipeline.ingest_documents()
    print(stats)
    for item in pipeline.retrieve_context("How do I reset my password?"):
        print(item["source"], item.get("page"), round(item["score"], 3))
