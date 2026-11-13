"""Small configuration regressions for portable handoff settings."""

from pathlib import Path

import pytest

from app.config import AS_OF_DATE, load_settings


def test_external_cache_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Explicit cache settings keep runtime files outside a checkout."""
    monkeypatch.setenv("AS_OF_DATE", AS_OF_DATE.isoformat())
    for name in ("MODEL_CACHE_DIR", "EMBEDDING_CACHE_DIR", "TRACE_DIR", "LLM_CACHE_DIR"):
        monkeypatch.setenv(name, str(tmp_path/name))
    settings = load_settings()
    assert settings.model_cache_dir == tmp_path/"MODEL_CACHE_DIR"
    assert settings.cache_dir == tmp_path/"EMBEDDING_CACHE_DIR"
    assert settings.trace_dir == tmp_path/"TRACE_DIR"
    assert settings.llm_cache_dir == tmp_path/"LLM_CACHE_DIR"


def test_date_override_cannot_change_verified_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    """Documented environment dates cannot silently invalidate ground truth."""
    monkeypatch.setenv("AS_OF_DATE", "2030-01-01")
    with pytest.raises(ValueError, match="frozen snapshot"):
        load_settings()
