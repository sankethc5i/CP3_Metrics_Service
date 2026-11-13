"""Deterministic warehouse configuration independent of the host clock."""

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Final
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ROOT: Final = Path(__file__).resolve().parents[1]
AS_OF_DATE: Final = date(2026, 11, 1)
START_DATE: Final = date(2025, 5, 1)
SEED: Final = 20261101
DATABASE_PATH: Final = ROOT / "data" / "ecommerce.db"
CATALOG_PATH: Final = ROOT / "semantic" / "metrics.yaml"
DEFAULT_EMBEDDING_MODELS: Final = {
    "local":"sentence-transformers/all-MiniLM-L6-v2",
    "openai":"text-embedding-3-small",
}


class ModelPrice(BaseModel):
    """User-supplied USD prices per million tokens; no assumed model pricing."""

    model_config = ConfigDict(extra="forbid")
    input_per_million: Decimal = Field(ge=0, allow_inf_nan=False)
    output_per_million: Decimal = Field(ge=0, allow_inf_nan=False)
    cached_input_per_million: Decimal | None = Field(default=None, ge=0, allow_inf_nan=False)


class Settings(BaseModel):
    """Runtime controls; credentials are intentionally absent from this model."""

    model_config = ConfigDict(extra="forbid")
    rag_mode: Literal["lookup", "naive", "hybrid", "hybrid_rerank", "corrective"] = "hybrid"
    model: str = "gpt-4.1-mini"
    embedding_provider: Literal["openai", "local"] = "local"
    embedding_model: str = ""
    top_k: int = Field(default=6, ge=1, le=30)
    max_rows: int = Field(default=100, ge=1, le=500)
    session_rate_limit: int = Field(default=5, ge=1, le=100)
    session_rate_window_seconds: float = Field(default=60, ge=1, le=3600)
    query_timeout: float = Field(default=3.0, gt=0, le=30)
    api_timeout: float = Field(default=40.0, gt=0, le=120)
    database: Path = DATABASE_PATH
    trace_dir: Path = ROOT / "data" / "traces"
    cache_dir: Path = ROOT / "data" / "embedding_cache"
    model_cache_dir: Path = ROOT / "data" / "models"
    rerank_enabled: bool = True
    rerank_model: str = "cross-encoder/ms-marco-MiniLM-L6-v2"
    candidate_k: int = Field(default=25,ge=20,le=30)
    evidence_k: int = Field(default=10,ge=1,le=10)
    rerank_batch_size: int = Field(default=16,ge=1,le=32)
    rerank_timeout: float = Field(default=30,gt=0,le=120)
    retrieval_timeout: float = Field(default=30,gt=0,le=120)
    request_timeout: float = Field(default=120,gt=0,le=300)
    max_retrieval_rounds: int = Field(default=2,ge=1,le=2)
    max_llm_calls: int = Field(default=4,ge=1,le=6)
    max_output_tokens: int = Field(default=6000,ge=500,le=12000)
    max_prompt_bytes: int = Field(default=24000,ge=4000,le=64000)
    select_tokens: int = Field(default=2000,ge=200,le=3000)
    answer_tokens: int = Field(default=1200,ge=200,le=3000)
    grade_tokens: int = Field(default=1200,ge=200,le=2000)
    rewrite_tokens: int = Field(default=500,ge=100,le=1000)
    evidence_confidence: float = Field(default=0.65,ge=0,le=1)
    external_sources_enabled: Literal[False] = False
    llm_cache_dir: Path = ROOT / "data" / "llm_cache"
    model_prices: dict[str, ModelPrice] = Field(default_factory=dict)

    @model_validator(mode="after")
    def resolve_embedding_model(self) -> "Settings":
        """Use the selected provider's default only when its model is unspecified."""
        if not self.embedding_model.strip():
            self.embedding_model = DEFAULT_EMBEDDING_MODELS[self.embedding_provider]
        return self


def load_settings() -> Settings:
    """Load local dotenv without overriding existing environment settings."""
    import os
    import json
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env", override=False)
    if (os.getenv("AS_OF_DATE") or AS_OF_DATE.isoformat()) != AS_OF_DATE.isoformat():
        raise ValueError("AS_OF_DATE must match the frozen snapshot: 2026-11-01.")
    controls = {}
    for variable, field in (("MODEL_CACHE_DIR", "model_cache_dir"),
                            ("EMBEDDING_CACHE_DIR", "cache_dir"),
                            ("TRACE_DIR", "trace_dir"), ("LLM_CACHE_DIR", "llm_cache_dir")):
        if os.getenv(variable):
            controls[field] = Path(os.environ[variable]).expanduser().resolve()
    for name in ("RERANK_ENABLED","RERANK_MODEL","CANDIDATE_K","EVIDENCE_K","RERANK_BATCH_SIZE",
        "RERANK_TIMEOUT","RETRIEVAL_TIMEOUT","REQUEST_TIMEOUT","MAX_RETRIEVAL_ROUNDS","MAX_LLM_CALLS",
        "MAX_OUTPUT_TOKENS","MAX_PROMPT_BYTES","SELECT_TOKENS","ANSWER_TOKENS","GRADE_TOKENS","REWRITE_TOKENS","EVIDENCE_CONFIDENCE",
        "SESSION_RATE_LIMIT","SESSION_RATE_WINDOW_SECONDS"):
        if os.getenv(name):
            controls[name.lower()] = os.environ[name]
    return Settings(
        rag_mode=os.getenv("RAG_MODE") or "hybrid",
        model=os.getenv("OPENAI_MODEL") or "gpt-4.1-mini",
        embedding_provider=os.getenv("EMBEDDING_PROVIDER") or "local",
        embedding_model=os.getenv("OPENAI_EMBEDDING_MODEL") or "",
        database=ROOT / (os.getenv("SQLITE_PATH") or "data/ecommerce.db"),
        model_prices=json.loads(os.getenv("MODEL_PRICES_JSON") or "{}"),
        **controls,
    )
