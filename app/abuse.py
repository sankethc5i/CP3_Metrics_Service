"""Small process-local admission control for a Streamlit session."""

import time


def admit_request(history: list[float], limit: int, window_seconds: float,
                  now: float | None = None) -> bool:
    """Prune a sliding window and admit at most limit submissions per session."""
    stamp = time.monotonic() if now is None else now
    history[:] = [t for t in history if stamp-window_seconds < t <= stamp]
    if len(history) >= limit:
        return False
    history.append(stamp)
    return True
