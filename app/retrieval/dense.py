"""Pluggable embeddings with provider/model/text-addressed caching and cosine search."""

from dataclasses import dataclass, field
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
from typing import Protocol

from app.retrieval.chunks import Chunk, Hit
from app.observability.startup import startup_step


@dataclass
class EmbeddingBatch:
    """Provider embeddings and actual provider-reported token usage."""

    vectors: list[list[float]]
    tokens: dict[str,int] = field(default_factory=dict)


class EmbeddingProvider(Protocol):
    """Minimal injectable interface for real and deterministic test embeddings."""

    name: str

    def embed(self, texts: list[str]) -> EmbeddingBatch:
        """Embed input texts in their original order."""
        ...


def _valid(vector: object) -> bool:
    return isinstance(vector,list) and bool(vector) and all(isinstance(v,(int,float)) and math.isfinite(v) for v in vector) and any(vector)


def cache_key(provider: str, model: str, text: str) -> str:
    """Hash provider, model and text hash; v2 never reads legacy OpenAI v1 keys."""
    text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    identity = json.dumps(["v2",provider,model,text_hash],separators=(",",":"))
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


class DenseRetriever:
    """Disk-cached, dense-only retrieval; no keyword fallback or reranking."""

    def __init__(self, chunks: list[Chunk], provider: EmbeddingProvider, model: str, cache: Path) -> None:
        self.chunks,self.provider,self.model,self.cache = chunks,provider,model,cache
        self.tokens: dict[str,int] = {}

    def _vectors(self, texts: list[str]) -> list[list[float]]:
        self.cache.mkdir(parents=True,exist_ok=True)
        paths = [self.cache/(cache_key(self.provider.name,self.model,text)+".json") for text in texts]
        vectors: list[list[float] | None] = []
        for path in paths:
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
                vectors.append(value if _valid(value) else None)
            except (OSError,ValueError):
                vectors.append(None)
        missing = [i for i,v in enumerate(vectors) if v is None]
        if missing:
            startup_step("Building embedding index/cache: encoding missing vectors")
            batch = self.provider.embed([texts[i] for i in missing])
            if len(batch.vectors) != len(missing) or not all(_valid(v) for v in batch.vectors):
                raise ValueError("Embedding provider returned invalid vectors")
            for key,value in batch.tokens.items():
                self.tokens[key] = self.tokens.get(key,0)+value
            for i,vector in zip(missing,batch.vectors):
                vectors[i] = vector
                with tempfile.NamedTemporaryFile(mode="w",encoding="utf-8",dir=self.cache,delete=False) as stream:
                    json.dump(vector,stream,allow_nan=False)
                    temporary = stream.name
                os.replace(temporary,paths[i])
            startup_step("Embedding index/cache ready")
        return [v for v in vectors if v is not None]

    def search(self, question: str, k: int = 6) -> list[Hit]:
        """Compute cosine scores from cached catalog and question embeddings."""
        self.tokens = {}
        vectors = self._vectors([c.text for c in self.chunks]+[question])
        query = vectors[-1]
        if any(len(v) != len(query) for v in vectors):
            raise ValueError("Embedding dimensions differ; cache/model mismatch")
        norm = math.sqrt(sum(v*v for v in query))
        scored = [(c,sum(a*b for a,b in zip(vector,query))/(math.sqrt(sum(v*v for v in vector))*norm))
            for c,vector in zip(self.chunks,vectors[:-1])]
        scored.sort(key=lambda p:(-p[1],p[0].id))
        return [Hit(c,s,{"dense":i},{"dense":s}) for i,(c,s) in enumerate(scored[:k],1)]

