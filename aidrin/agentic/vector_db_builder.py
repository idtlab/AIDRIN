"""
VectorDBBuilder: ingest text/PDF documents, chunk, embed, and persist a FAISS vector index.

Config (YAML) expects a ``vector_store`` section:

.. code-block:: yaml

    vector_store:
      sources:
        - "./docs"
        - "./notes.txt"
      embedding_model: text-embedding-3-small
      chunk_size: 500
      chunk_overlap: 50
      vector_store_name: my_vector_store   # name for the output directory

Requires ``OPENAI_API_KEY`` (or ``GOOGLE_API_KEY`` for Gemini embedding models).
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import yaml

try:
    import faiss  # type: ignore
except Exception:
    faiss = None

try:
    import PyPDF2
except ImportError:
    PyPDF2 = None

try:
    from langchain_openai import OpenAIEmbeddings
    from langchain_text_splitters import RecursiveCharacterTextSplitter
except ImportError as exc:
    raise ImportError(
        "langchain-openai and langchain-text-splitters are required. "
        "Install with: pip install 'aidrin[agentic]'"
    ) from exc

try:
    from langchain_google_genai import GoogleGenerativeAIEmbeddings
except ImportError:
    GoogleGenerativeAIEmbeddings = None  # type: ignore


def _make_embeddings(
    model_name: str,
    openai_api_key: str | None = None,
    google_api_key: str | None = None,
    base_url: str | None = None,
):
    if "gemini" in model_name or "embedding-001" in model_name:
        if GoogleGenerativeAIEmbeddings is None:
            raise ImportError(
                "langchain-google-genai is required for Gemini embeddings. "
                "Install with: pip install langchain-google-genai"
            )
        kwargs: dict[str, Any] = {"model": model_name}
        if google_api_key:
            kwargs["google_api_key"] = google_api_key
        return GoogleGenerativeAIEmbeddings(**kwargs)

    kwargs: dict[str, Any] = {"model": model_name}
    if openai_api_key:
        kwargs["api_key"] = openai_api_key
    if base_url:
        kwargs["base_url"] = base_url
    model = OpenAIEmbeddings(**kwargs)
    if not base_url:
        return model

    # Wrap with fallback to standard OpenAI when a custom endpoint is configured.
    fallback_kwargs: dict[str, Any] = {"model": model_name}
    if openai_api_key:
        fallback_kwargs["api_key"] = openai_api_key
    fallback = OpenAIEmbeddings(**fallback_kwargs)

    import sys as _sys

    class _FallbackEmbeddings:
        def embed_documents(self, texts: list[str]) -> list[list[float]]:
            try:
                return model.embed_documents(texts)
            except Exception as exc:
                _sys.stderr.write(f"[aidrin] Embedding via custom endpoint failed ({exc}); falling back to OpenAI API.\n")
                return fallback.embed_documents(texts)

        def embed_query(self, text: str) -> list[float]:
            try:
                return model.embed_query(text)
            except Exception as exc:
                _sys.stderr.write(f"[aidrin] Embedding via custom endpoint failed ({exc}); falling back to OpenAI API.\n")
                return fallback.embed_query(text)

    return _FallbackEmbeddings()


class VectorDBBuilder:
    """Build a simple vector index from configured document sources."""

    def __init__(self, config_path: Path | str) -> None:
        self.config_path = Path(config_path)
        cfg = self._load_config(self.config_path)
        self.sources: list[Path] = cfg["sources"]
        self.embedding_model_name: str = cfg["embedding_model"]
        self.openai_api_key = cfg["openai_api_key"]
        self.google_api_key = cfg["google_api_key"]
        self.base_url: str | None = cfg["base_url"]
        self.chunk_size: int = cfg["chunk_size"]
        self.chunk_overlap: int = cfg["chunk_overlap"]
        self.output_dir: Path = cfg["output_dir"]
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.metadata_path = self.output_dir / "metadata.json"
        self.index_path = self.output_dir / "index.faiss"
        self.embeddings_path = self.output_dir / "embeddings.npy"

    def exists(self) -> bool:
        return self.metadata_path.exists() and self.embeddings_path.exists()

    @staticmethod
    def _load_config(config_path: Path) -> dict[str, Any]:
        with config_path.open("r", encoding="utf-8") as fh:
            cfg = yaml.safe_load(fh) or {}
        vector_cfg = cfg.get("vector_store") or {}
        sources = vector_cfg.get("sources", [])
        embedding_model = vector_cfg.get("embedding_model")
        llm_cfg = cfg.get("llm", {}) or {}
        openai_api_key = (
            vector_cfg.get("openai_api_key")
            or llm_cfg.get("api_key")
            or os.environ.get("OPENAI_API_KEY")
        )
        google_api_key = vector_cfg.get("google_api_key") or os.environ.get("GOOGLE_API_KEY")
        base_url = llm_cfg.get("base_url") or os.environ.get("OPENAI_BASE_URL")
        if not embedding_model:
            raise ValueError("vector_store.embedding_model must be set in the config YAML.")
        if not sources:
            raise ValueError("vector_store.sources must list files or directories to index.")

        resolved_sources: list[Path] = []
        base = config_path.parent
        for src in sources:
            p = Path(src)
            candidates = []
            if p.is_absolute():
                candidates = [p]
            else:
                candidates = [(base / p).resolve(), (base.parent / p).resolve()]
            found = next((c for c in candidates if c.exists()), None)
            if not found:
                raise FileNotFoundError(f"Source path not found: {candidates[0]}")
            resolved_sources.append(found)

        chunk_size = int(vector_cfg.get("chunk_size", 500))
        chunk_overlap = int(vector_cfg.get("chunk_overlap", 50))
        store_name = vector_cfg.get("vector_store_name", "vector_store")
        default_output = (base.parent / store_name).resolve()
        output_dir = vector_cfg.get("vector_store_dir", default_output)
        output_dir = (Path(output_dir) if Path(output_dir).is_absolute() else (base / output_dir).resolve())

        return {
            "sources": resolved_sources,
            "embedding_model": embedding_model,
            "openai_api_key": openai_api_key,
            "google_api_key": google_api_key,
            "base_url": base_url,
            "vector_store_name": store_name,
            "chunk_size": chunk_size,
            "chunk_overlap": chunk_overlap,
            "output_dir": output_dir,
        }

    def _gather_files(self) -> list[Path]:
        files: list[Path] = []
        for src in self.sources:
            if src.is_dir():
                for ext in ("*.txt", "*.pdf"):
                    files.extend(src.rglob(ext))
            else:
                files.append(src)
        seen: set[Path] = set()
        unique: list[Path] = []
        for f in files:
            if f not in seen:
                unique.append(f)
                seen.add(f)
        return unique

    def _read_text(self, path: Path) -> str:
        suffix = path.suffix.lower()
        if suffix == ".pdf":
            try:
                import fitz  # PyMuPDF
            except ImportError:
                raise ImportError(
                    "PyMuPDF is required for PDF parsing. Install with: pip install pymupdf"
                )
            text = ""
            with fitz.open(str(path)) as doc:
                for page in doc:
                    text += page.get_text() + "\n"
            return text
        return path.read_text(encoding="utf-8", errors="ignore")

    def _chunk(self, text: str) -> list[str]:
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            length_function=len,
        )
        return splitter.split_text(text)

    def _embed(self, texts: list[str]) -> tuple[list[list[float]], int]:
        model = _make_embeddings(self.embedding_model_name, self.openai_api_key, self.google_api_key, self.base_url)
        vectors = model.embed_documents(texts)
        dims = len(vectors[0]) if vectors else 0
        return vectors, dims

    def _save_index(self, embeddings: list[list[float]], dims: int, metadata: list[dict[str, Any]]) -> None:
        with self.metadata_path.open("w", encoding="utf-8") as fh:
            json.dump(metadata, fh, indent=2)

        import numpy as np
        emb_array = np.array(embeddings, dtype="float32")
        np.save(self.embeddings_path, emb_array)

        if faiss is None or dims == 0:
            return

        index = faiss.IndexFlatL2(dims)
        index.add(emb_array)
        faiss.write_index(index, str(self.index_path))

    def build(self) -> dict[str, Any]:
        """Build and persist the vector index. Returns a summary dict."""
        is_gemini = "gemini" in self.embedding_model_name or "embedding-001" in self.embedding_model_name
        if is_gemini:
            if not (self.google_api_key or "GOOGLE_API_KEY" in os.environ):
                raise ValueError("Google API key missing. Set GOOGLE_API_KEY environment variable.")
        elif not (self.openai_api_key or "OPENAI_API_KEY" in os.environ):
            raise ValueError("OpenAI API key missing. Set OPENAI_API_KEY environment variable.")

        files = self._gather_files()
        all_chunks: list[str] = []
        meta: list[dict[str, Any]] = []
        for path in files:
            text = self._read_text(path)
            chunks = self._chunk(text)
            for idx, chunk in enumerate(chunks):
                if not chunk or not chunk.strip():
                    continue
                meta.append({"source": str(path), "chunk_id": idx, "text": chunk})
                all_chunks.append(chunk)

        if not all_chunks:
            raise ValueError("No text could be extracted from the provided sources.")

        embeddings, dims = self._embed(all_chunks)
        self._save_index(embeddings, dims, meta)

        return {
            "files_indexed": len(files),
            "chunks": len(all_chunks),
            "embedding_model": self.embedding_model_name,
            "output_dir": str(self.output_dir),
            "index_path": str(self.index_path) if faiss else None,
            "embeddings_path": str(self.embeddings_path),
            "metadata_path": str(self.metadata_path),
            "faiss_enabled": faiss is not None,
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a vector DB from documents.")
    parser.add_argument("-c", "--config", type=Path, required=True,
                        help="YAML config with a vector_store section.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    builder = VectorDBBuilder(args.config)
    result = builder.build()
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
