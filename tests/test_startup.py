"""Startup configuration and cached-index checks without downloads or API calls."""

from pathlib import Path
from unittest.mock import patch

import pytest

from app.config import ROOT, load_settings
from app.retrieval.index import load_catalog_index


def test_catalog_index_resource_cached(warehouse: Path) -> None:
    """Repeated requests reuse the index until a catalog/database revision changes."""
    from app.semantic.loader import load_catalog
    load_catalog_index.clear()
    try:
        with patch("app.retrieval.index.load_catalog",wraps=load_catalog) as loader:
            first = load_catalog_index(str(warehouse),1,1)
            second = load_catalog_index(str(warehouse),1,1)
            assert first is second
            assert loader.call_count==1
            load_catalog_index(str(warehouse),1,2)
            assert loader.call_count==2
    finally:
        load_catalog_index.clear()


def test_dotenv_loads_blank_defaults(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing credentials and blank settings allow the initial UI to render."""
    monkeypatch.setattr("app.config.ROOT",tmp_path)
    for name in ("OPENAI_API_KEY","OPENAI_MODEL","EMBEDDING_PROVIDER","OPENAI_EMBEDDING_MODEL","RAG_MODE","SQLITE_PATH"):
        monkeypatch.delenv(name,raising=False)
    (tmp_path/".env").write_text("RAG_MODE=lookup\nEMBEDDING_PROVIDER=\nOPENAI_EMBEDDING_MODEL=\nOPENAI_API_KEY=\nSQLITE_PATH=\n")
    settings = load_settings()
    assert settings.rag_mode=="lookup"
    assert settings.embedding_provider=="local"
    assert settings.embedding_model.endswith("all-MiniLM-L6-v2")
    assert settings.database==tmp_path/"data"/"ecommerce.db"
