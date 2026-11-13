"""Reciprocal-rank fusion with original per-retriever score/rank evidence."""

from app.retrieval.chunks import Hit


def rrf(results: dict[str,list[Hit]], k: int = 6, constant: int = 60) -> list[Hit]:
    """Fuse independent ranks without score normalization or a reranking model."""
    if constant < 1:
        raise ValueError("RRF constant must be positive")
    merged: dict[str,Hit] = {}
    for name,hits in results.items():
        seen: set[str] = set()
        for hit in hits:
            if hit.chunk.id in seen:
                continue
            rank = len(seen)+1
            seen.add(hit.chunk.id)
            fused = merged.setdefault(hit.chunk.id,Hit(hit.chunk,0.0))
            fused.score += 1/(constant+rank)
            fused.ranks[name] = rank
            fused.scores[name] = hit.score
    return sorted(merged.values(),key=lambda hit:(-hit.score,hit.chunk.id))[:k]
