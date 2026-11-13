"""Switchable retrieval modes over one catalog corpus."""

from typing import Literal

from app.retrieval.chunks import Chunk, Hit
from app.retrieval.dense import DenseRetriever
from app.retrieval.fusion import rrf
from app.retrieval.lexical import BM25Retriever, LookupRetriever


class RetrievalEngine:
    """Lookup baseline, dense-only naive RAG, or lookup/BM25/dense RRF."""

    def __init__(self, chunks: list[Chunk], dense: DenseRetriever | None = None) -> None:
        self.lookup = LookupRetriever(chunks)
        self.bm25 = BM25Retriever(chunks)
        self.dense = dense
        self.tokens: dict[str,int] = {}

    def search(self, question: str, mode: str, k: int = 6) -> list[Hit]:
        """Run exactly the configured retrievers and report provider token usage."""
        self.tokens = {}
        if mode in {"hybrid_rerank","corrective"}:
            return self.candidates(question,k)
        if mode == "lookup":
            return self.lookup.search(question,k)
        if mode not in {"naive","hybrid"}:
            raise ValueError("Unknown RAG mode")
        if self.dense is None:
            raise ValueError("Dense retrieval requires an embedding provider")
        depth = k if mode == "naive" else max(k*3,20)
        dense = self.dense.search(question,depth)
        self.tokens = dict(self.dense.tokens)
        if mode == "naive":
            return dense
        return rrf({"lookup":self.lookup.search(question,depth),"bm25":self.bm25.search(question,depth),"dense":dense},k)

    def candidates(self, question: str, k: int = 25) -> list[Hit]:
        """Return bounded unique dense+BM25 RRF candidates, excluding the lookup scorer."""
        if self.dense is None:
            raise ValueError("Dense retrieval requires an embedding provider")
        size = min(k,len(self.lookup.chunks))
        depth = min(size*2,len(self.lookup.chunks))
        dense = self.dense.search(question,depth)
        self.tokens = dict(self.dense.tokens)
        return rrf({"bm25":self.bm25.search(question,depth),"dense":dense},size)
