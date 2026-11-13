"""Provider selection, resource reuse and safe failures using only stub embedders."""

import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from collections.abc import Iterator
from unittest.mock import Mock, patch

import pytest

from app.config import DEFAULT_EMBEDDING_MODELS, ROOT, Settings, load_settings
from app.retrieval.chunks import Chunk
from app.retrieval.dense import DenseRetriever, cache_key
from app.retrieval.providers import (
    EmbeddingUnavailableError, LocalEmbedder, OpenAIEmbedder, create_embedder, load_local_model,
)
from tests.test_retrieval import FakeEmbeddings, chunks


@pytest.fixture(autouse=True)
def isolated_model_cache() -> Iterator[None]:
    """Never allow one stub model to survive into another test's resource cache."""
    load_local_model.clear()
    yield
    load_local_model.clear()


def test_empty_environment_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """Blank template values use local MiniLM/hybrid and a real database path."""
    for key in ("EMBEDDING_PROVIDER","OPENAI_EMBEDDING_MODEL","RAG_MODE","SQLITE_PATH"):
        monkeypatch.setenv(key,"")
    with patch("dotenv.load_dotenv"):
        settings = load_settings()
    assert settings.embedding_provider=="local"
    assert settings.embedding_model==DEFAULT_EMBEDDING_MODELS["local"]
    assert settings.rag_mode=="hybrid"
    assert settings.database==ROOT/"data"/"ecommerce.db"
    assert Settings(embedding_provider="openai").embedding_model=="text-embedding-3-small"


def test_explicit_environment_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    """The existing model setting configures either provider consistently."""
    monkeypatch.setenv("EMBEDDING_PROVIDER","openai")
    monkeypatch.setenv("OPENAI_EMBEDDING_MODEL","authorized-model")
    monkeypatch.setenv("RAG_MODE","naive")
    with patch("dotenv.load_dotenv"):
        settings = load_settings()
    assert (settings.embedding_provider,settings.embedding_model,settings.rag_mode)==("openai","authorized-model","naive")


def test_local_model_loaded_once_without_key(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Separate local adapters share one Streamlit-cached stub model, without API use."""
    monkeypatch.delenv("OPENAI_API_KEY",raising=False)
    model = Mock()
    model.encode.return_value = SimpleNamespace(tolist=lambda:[[0.6,0.8]])
    constructor = Mock(return_value=model)
    monkeypatch.setitem(sys.modules,"sentence_transformers",SimpleNamespace(SentenceTransformer=constructor))
    client = Mock()
    settings = Settings(model_cache_dir=tmp_path)
    first = create_embedder(settings,client)
    second = create_embedder(settings,client)
    assert isinstance(first,LocalEmbedder) and isinstance(second,LocalEmbedder)
    assert first.embed(["metric"]).vectors==[[0.6,0.8]]
    assert second.embed(["dimension"]).tokens["total_tokens"]==0
    constructor.assert_called_once_with(settings.embedding_model,local_files_only=True,device="cpu",cache_folder=str(tmp_path),trust_remote_code=False,token=False)
    assert model.encode.call_count==2
    client.embed.assert_not_called()


@pytest.mark.parametrize("error",[ImportError("private import detail"),OSError("private model download detail")])
def test_local_unavailable_no_fallback(error: Exception, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Missing package/model failures expose setting names without provider details."""
    monkeypatch.setitem(sys.modules,"sentence_transformers",SimpleNamespace(SentenceTransformer=Mock(side_effect=error)))
    client = Mock()
    embedder = create_embedder(Settings(model_cache_dir=tmp_path),client)
    with pytest.raises(EmbeddingUnavailableError) as caught:
        embedder.embed(["metric"])
    message = str(caught.value)
    assert "EMBEDDING_PROVIDER" in message and "OPENAI_EMBEDDING_MODEL" in message
    assert "private" not in message
    client.embed.assert_not_called()


def test_openai_failure_does_not_load_local() -> None:
    """An unavailable chosen OpenAI provider never calls the local loader."""
    client = Mock()
    client.embed.side_effect = RuntimeError("private API detail")
    provider = create_embedder(Settings(embedding_provider="openai"),client)
    assert isinstance(provider,OpenAIEmbedder)
    with patch("app.retrieval.providers.load_local_model") as local:
        with pytest.raises(EmbeddingUnavailableError,match="EMBEDDING_PROVIDER=local"):
            provider.embed(["metric"])
        local.assert_not_called()


def test_provider_and_legacy_cache_isolation(chunks: list[Chunk], tmp_path: Path) -> None:
    """Equal model/text with different providers and old OpenAI cache files cannot mix."""
    text,model = "conversion visits","same-model"
    for content in [c.text for c in chunks]+[text]:
        old_key = hashlib.sha256(("v1\0"+model+"\0"+content).encode()).hexdigest()
        (tmp_path/(old_key+".json")).write_text(json.dumps([1.0,0.0]))
    openai = FakeEmbeddings(name="openai")
    local = FakeEmbeddings(name="local")
    DenseRetriever(chunks,openai,model,tmp_path).search(text)
    DenseRetriever(chunks,local,model,tmp_path).search(text)
    assert len(openai.calls)==len(local.calls)==1
    assert cache_key("openai",model,text)!=cache_key("local",model,text)
    DenseRetriever(chunks,local,model,tmp_path).search(text)
    assert len(local.calls)==1
    changed = FakeEmbeddings(name="local")
    DenseRetriever(chunks,changed,model,tmp_path).search(text+" changed")
    assert changed.calls==[[text+" changed"]]


def test_example_has_only_empty_values() -> None:
    """The committed environment template contains variable names and no defaults/secrets."""
    lines = [line for line in (ROOT/".env.example").read_text().splitlines() if line and not line.startswith("#")]
    assert all(line.endswith("=") for line in lines)
    assert "EMBEDDING_PROVIDER=" in lines and "OPENAI_EMBEDDING_MODEL=" in lines
