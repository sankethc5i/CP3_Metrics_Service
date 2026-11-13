"""Cached local cross-encoder scoring of bounded catalog candidate pairs."""

from concurrent.futures import ThreadPoolExecutor, TimeoutError
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import threading
from typing import Any, Protocol

import streamlit as st

from app.retrieval.chunks import Hit
from app.retrieval.providers import LocalModelResource


class RerankUnavailable(RuntimeError):
    """A configured reranker cannot run; never silently substitute another model."""


class PairScorer(Protocol):
    """Injectable cross-encoder interface for offline stub tests."""

    def score(self, question: str, passages: list[str], timeout: float) -> list[float]:
        """Batch-score question/passage pairs."""
        ...


@st.cache_resource(show_spinner=False)
def load_cross_encoder(model: str, cache: str) -> LocalModelResource:
    """Load one local CPU cross-encoder per model/cache directory."""
    try:
        from sentence_transformers import CrossEncoder
        options = dict(device="cpu",cache_folder=cache,trust_remote_code=False,token=False)
        try:
            encoder = CrossEncoder(model,local_files_only=True,**options)
        except OSError:
            encoder = CrossEncoder(model,**options)
        return LocalModelResource(encoder)
    except Exception:
        raise RerankUnavailable("Reranker unavailable. Check RERANK_MODEL or disable RERANK_ENABLED.") from None


@st.cache_resource(show_spinner=False)
def _worker() -> tuple[ThreadPoolExecutor,threading.BoundedSemaphore]:
    return ThreadPoolExecutor(max_workers=1,thread_name_prefix="catalog-reranker"),threading.BoundedSemaphore(1)


class LocalCrossEncoder:
    """Batch inference with a bounded worker and deadline, including cold loading."""

    def __init__(self, model: str, cache: Path, batch_size: int = 16) -> None:
        self.model,self.cache,self.batch_size = model,cache,batch_size

    def warmup(self) -> None:
        """Load the configured local resource before timed benchmark questions."""
        load_cross_encoder(self.model,str(self.cache))

    def score(self, question: str, passages: list[str], timeout: float) -> list[float]:
        """Bound waiting time without accumulating jobs behind timed-out inference."""
        executor,slot = _worker()
        if not slot.acquire(blocking=False):
            raise RerankUnavailable("Reranker is still busy. Retry later or disable RERANK_ENABLED.")
        def infer() -> list[float]:
            resource = load_cross_encoder(self.model,str(self.cache))
            with resource.lock:
                return [float(value) for value in resource.model.predict(
                    [(question,text) for text in passages],batch_size=self.batch_size,show_progress_bar=False)]
        future = executor.submit(infer)
        future.add_done_callback(lambda _:slot.release())
        try:
            return future.result(timeout=timeout)
        except TimeoutError:
            raise RerankUnavailable("Reranking timed out. Adjust RERANK_TIMEOUT or disable RERANK_ENABLED.") from None
        except RerankUnavailable:
            raise
        except Exception:
            raise RerankUnavailable("Reranking failed. Check RERANK_MODEL or disable RERANK_ENABLED.") from None


class Reranker:
    """Cache pair scores by cross-encoder model, query hash and chunk-text hash."""

    def __init__(self, scorer: PairScorer, model: str, cache: Path) -> None:
        self.scorer,self.model,self.cache = scorer,model,cache

    def rerank(self, question: str, hits: list[Hit], keep: int = 10, timeout: float = 20) -> list[Hit]:
        """Batch missing pairs, preserve retrieval evidence and keep a stable top ten."""
        unique = list({hit.chunk.id:hit for hit in hits}.values())
        self.cache.mkdir(parents=True,exist_ok=True)
        paths = [self.cache/(hashlib.sha256(json.dumps(["cross-v1",self.model,
            hashlib.sha256(question.encode()).hexdigest(),hashlib.sha256(h.chunk.text.encode()).hexdigest()]).encode()).hexdigest()+".json") for h in unique]
        values: list[float | None] = []
        for path in paths:
            try:
                value = json.loads(path.read_text())
                values.append(float(value) if isinstance(value,(int,float)) and math.isfinite(value) else None)
            except (OSError,ValueError):
                values.append(None)
        missing = [i for i,v in enumerate(values) if v is None]
        if missing:
            scores = self.scorer.score(question,[unique[i].chunk.text for i in missing],timeout)
            if len(scores)!=len(missing) or not all(math.isfinite(v) for v in scores):
                raise RerankUnavailable("Invalid reranker scores. Check RERANK_MODEL.")
            for index,value in zip(missing,scores):
                values[index] = float(value)
                with tempfile.NamedTemporaryFile(mode="w",dir=self.cache,delete=False) as stream:
                    json.dump(value,stream)
                    temporary = stream.name
                os.replace(temporary,paths[index])
        ordered = sorted(zip(unique,values),key=lambda pair:(-float(pair[1]),pair[0].chunk.id))[:keep]
        return [Hit(hit.chunk,float(value),{**hit.ranks,"rerank":rank},{**hit.scores,"rerank":float(value)})
            for rank,(hit,value) in enumerate(ordered,1)]
