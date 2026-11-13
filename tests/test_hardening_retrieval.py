"""Controlled lexical, vector and fusion tests, including ties and missing results."""

from pathlib import Path

import pytest

from app.retrieval.chunks import Chunk, Hit
from app.retrieval.dense import DenseRetriever, EmbeddingBatch
from app.retrieval.fusion import rrf
from app.retrieval.lexical import BM25Retriever, LookupRetriever

CORPUS = [Chunk("a", "metric", "net revenue retained sales", {"aliases": ["net revenue", "retained sales"]}),
          Chunk("b", "metric", "conversion visits", {"aliases": ["conversion rate"]})]


@pytest.mark.parametrize("retriever", [LookupRetriever, BM25Retriever])
@pytest.mark.parametrize("question", ["net revenue", "retained sales", "nett revenue"])
def test_lexical_queries_and_partial_typos(retriever: type, question: str) -> None:
    """Exact, synonym and partial-typo queries retain lexical evidence."""
    assert retriever(CORPUS).search(question)[0].chunk.id == "a"
    assert retriever(CORPUS).search("xyzzy flobble") == []


def test_lexical_ties_empty_corpora_and_full_typo() -> None:
    """Pure lexical baselines do not pretend to understand unrecognized typo tokens."""
    same = [Chunk("z", "metric", "same", {}), Chunk("a", "metric", "same", {})]
    for cls in (LookupRetriever, BM25Retriever):
        assert [h.chunk.id for h in cls(same).search("same")] == ["a", "z"]
        assert cls([]).search("anything") == []
        assert cls(CORPUS).search("nett revnue") == []


class ControlledVectors:
    """An explicit vector table isolates cosine ranking from real model quality."""

    name = "controlled"

    def embed(self, texts: list[str]) -> EmbeddingBatch:
        """Map authored paraphrases/typos to the same test semantic direction."""
        return EmbeddingBatch([[0., 1.] if text == CORPUS[1].text else [1., 0.] for text in texts])


@pytest.mark.parametrize("question", ["net revenue", "retained sales", "nett revnue"])
def test_dense_exact_synonym_and_typo_vectors(question: str, tmp_path: Path) -> None:
    """Dense tests assert vector ranking, not unsupported claims about real model accuracy."""
    hits = DenseRetriever(CORPUS, ControlledVectors(), "stub", tmp_path).search(question)
    assert [h.chunk.id for h in hits] == ["a", "b"]
    assert hits[0].score == 1 and hits[1].score == 0


def test_rrf_ties_missing_and_duplicate_results() -> None:
    """Missing retriever results add nothing and duplicates never boost a document."""
    a, b = Hit(CORPUS[0], 100), Hit(CORPUS[1], -99)
    assert rrf({"a": [], "b": []}) == []
    hits = rrf({"one": [a, b], "two": [b, a], "missing": []})
    assert [h.chunk.id for h in hits] == ["a", "b"]
    assert hits[0].score == hits[1].score == pytest.approx(1/61+1/62)
    unique = rrf({"one": [a, a, b]})
    assert unique[0].score == pytest.approx(1/61)
    assert unique[1].ranks["one"] == 2
