"""Independent catalog lookup, BM25, cached dense, mode and RRF tests."""

import hashlib
from pathlib import Path
from unittest.mock import patch

import pytest

from app.retrieval.chunks import Chunk, Hit, chunk_catalog
from app.retrieval.dense import DenseRetriever, EmbeddingBatch
from app.retrieval.engine import RetrievalEngine
from app.retrieval.fusion import rrf
from app.retrieval.lexical import BM25Retriever, LookupRetriever, tokenize
from app.semantic.loader import load_catalog


class FakeEmbeddings:
    """Deterministic test-only vectors; never substituted for production embeddings."""

    def __init__(self, name: str = "stub") -> None:
        self.name = name
        self.calls: list[list[str]] = []

    def embed(self, texts: list[str]) -> EmbeddingBatch:
        """Map token hashes to a fixed bag-of-words vector for local tests."""
        self.calls.append(texts)
        vectors = []
        for text in texts:
            vector = [0.0]*64
            for word in tokenize(text):
                vector[int(hashlib.sha256(word.encode()).hexdigest()[:8],16)%64] += 1
            vectors.append(vector)
        return EmbeddingBatch(vectors,{"input_tokens":sum(len(tokenize(t)) for t in texts),"output_tokens":0})


@pytest.fixture
def chunks() -> list[Chunk]:
    """Provide a tiny corpus whose lexical expectations are unambiguous."""
    return [Chunk("gross","metric","gross revenue sales",{"aliases":["gross sales"]}),
        Chunk("conversion","metric","conversion sessions visits",{"aliases":["conversion rate"]})]


def test_chunks_are_catalog_only(warehouse: Path) -> None:
    """Chunk boundaries include every definition and unique rule, with metadata."""
    catalog = load_catalog(database=warehouse)
    chunks = chunk_catalog(catalog)
    assert sum(c.kind=="metric" for c in chunks)==15
    assert sum(c.kind=="dimension" for c in chunks)==9
    assert len({c.id for c in chunks}) == len(chunks)
    assert all("SELECT" not in c.text for c in chunks)
    assert all(c.metadata.get("examples") for c in chunks if c.kind=="metric")
    for rule in {r for m in catalog.metrics for r in m.business_rules}:
        assert sum(c.kind=="rule" and c.text==rule for c in chunks)==1


def test_lookup_exact_synonym_and_keyword(chunks: list[Chunk]) -> None:
    """The baseline works without embeddings or statistical training."""
    lookup = LookupRetriever(chunks)
    assert lookup.search("gross sales")[0].chunk.id == "gross"
    assert lookup.search("visits")[0].chunk.id == "conversion"
    assert lookup.search("xyzunknown") == []


def test_bm25_independent(chunks: list[Chunk]) -> None:
    """BM25 ranks its lexical evidence and exposes original score and rank."""
    result = BM25Retriever(chunks).search("conversion visits")
    assert result[0].chunk.id == "conversion"
    assert result[0].score > 0 and result[0].ranks == {"bm25":1}


def test_dense_cache_and_model_invalidation(chunks: list[Chunk], tmp_path: Path) -> None:
    """Cache catalog/question vectors across instances and isolate model versions."""
    provider = FakeEmbeddings()
    dense = DenseRetriever(chunks,provider,"model-a",tmp_path)
    assert dense.search("conversion visits")[0].chunk.id == "conversion"
    assert len(provider.calls)==1
    assert dense.tokens["input_tokens"]>0
    rebuilt = DenseRetriever(chunks,provider,"model-a",tmp_path)
    rebuilt.search("conversion visits")
    assert len(provider.calls)==1 and rebuilt.tokens=={}
    DenseRetriever(chunks,provider,"model-b",tmp_path).search("conversion visits")
    assert len(provider.calls)==2
    # Files contain vectors only, without raw question text or warehouse data.
    assert all("conversion visits" not in p.read_text() for p in tmp_path.glob("*.json"))


def test_rrf_ranks_and_scores(chunks: list[Chunk]) -> None:
    """Fusion uses ranks and preserves original evidence; it does not rerank."""
    first = [Hit(chunks[0],99),Hit(chunks[1],3)]
    second = [Hit(chunks[1],0.9),Hit(chunks[0],0.5)]
    fused = rrf({"bm25":first,"dense":second},2)
    assert fused[0].score == pytest.approx(1/61+1/62)
    assert fused[0].ranks == {"bm25":2,"dense":1}
    assert fused[0].scores == {"bm25":3,"dense":0.9}


def test_switchable_modes(chunks: list[Chunk], tmp_path: Path) -> None:
    """Naive calls only dense; hybrid independently fuses all three retrievers."""
    dense = DenseRetriever(chunks,FakeEmbeddings(),"test",tmp_path)
    engine = RetrievalEngine(chunks,dense)
    with patch.object(engine.lookup,"search",wraps=engine.lookup.search) as lookup, patch.object(engine.bm25,"search",wraps=engine.bm25.search) as bm25:
        assert set(engine.search("conversion","lookup")[0].ranks)=={"lookup"}
        lookup.reset_mock()
        assert set(engine.search("conversion","naive")[0].ranks)=={"dense"}
        lookup.assert_not_called()
        bm25.assert_not_called()
        assert set(engine.search("conversion","hybrid")[0].ranks)=={"lookup","bm25","dense"}
