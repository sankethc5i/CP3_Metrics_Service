"""Local and OpenAI embedding adapters with explicit, safe availability failures."""

from dataclasses import dataclass, field
from pathlib import Path
import threading
from typing import Any

import streamlit as st

from app.config import Settings
from app.observability.startup import startup_step
from app.retrieval.dense import EmbeddingBatch, EmbeddingProvider


class EmbeddingUnavailableError(RuntimeError):
    """A provider failure whose message is safe to return to the user."""


@dataclass
class LocalModelResource:
    """Shared model plus lock for safe encoding across Streamlit sessions."""

    model: Any
    lock: Any = field(default_factory=threading.Lock)


@st.cache_resource(show_spinner=False)
def load_local_model(model: str, cache_folder: str) -> LocalModelResource:
    """Load a model once per name/cache directory; no API key or remote code."""
    try:
        startup_step("Loading local embedder dependencies")
        from sentence_transformers import SentenceTransformer
        startup_step("Loading local model (first use may download weights)")
        options = dict(device="cpu",cache_folder=cache_folder,trust_remote_code=False,token=False)
        try:
            encoder = SentenceTransformer(model,local_files_only=True,**options)
        except OSError:
            encoder = SentenceTransformer(model,**options)
        startup_step("Local embedder ready")
        return LocalModelResource(encoder)
    except Exception:
        raise EmbeddingUnavailableError(
            "Local embeddings are unavailable. Install the pinned sentence-transformers dependencies "
            "and check OPENAI_EMBEDDING_MODEL and model download/cache access, "
            "or change EMBEDDING_PROVIDER to an available provider.") from None


class LocalEmbedder:
    """Sentence Transformers embeddings computed locally without API credentials."""

    name = "local"

    def __init__(self, model: str, cache_folder: Path) -> None:
        self.model,self.cache_folder = model,cache_folder

    def embed(self, texts: list[str]) -> EmbeddingBatch:
        """Encode with the cached CPU model; report zero API token consumption."""
        try:
            resource = load_local_model(self.model,str(self.cache_folder))
            with resource.lock:
                vectors = resource.model.encode(texts,convert_to_numpy=True,
                    normalize_embeddings=True,show_progress_bar=False).tolist()
            return EmbeddingBatch(vectors,{"input_tokens":0,"output_tokens":0,"total_tokens":0})
        except EmbeddingUnavailableError:
            raise
        except Exception:
            raise EmbeddingUnavailableError(
                "Local embedding generation failed. Check OPENAI_EMBEDDING_MODEL "
                "or change EMBEDDING_PROVIDER to an available provider.") from None


class OpenAIEmbedder:
    """Wrap the existing lazy OpenAI adapter without exposing provider exceptions."""

    name = "openai"

    def __init__(self, client: Any) -> None:
        self.client = client

    def embed(self, texts: list[str]) -> EmbeddingBatch:
        """Request OpenAI vectors or fail explicitly, without local fallback."""
        try:
            return self.client.embed(texts)
        except Exception:
            raise EmbeddingUnavailableError(
                "OpenAI embeddings are unavailable. Check OPENAI_API_KEY and OPENAI_EMBEDDING_MODEL "
                "project access, or set EMBEDDING_PROVIDER=local.") from None


def create_embedder(settings: Settings, openai_client: Any) -> EmbeddingProvider:
    """Select exactly the configured provider; never probe or substitute another."""
    if settings.embedding_provider == "local":
        return LocalEmbedder(settings.embedding_model,settings.model_cache_dir)
    if settings.embedding_provider == "openai":
        return OpenAIEmbedder(openai_client)
    raise EmbeddingUnavailableError("Unsupported provider. Set EMBEDDING_PROVIDER to local or openai.")
