"""Optional budgeted live smoke: disabled by default even if a key is present."""

import os

import pytest


@pytest.mark.live
def test_live_dev_smoke(request: pytest.FixtureRequest) -> None:
    """Use the same confirmed, cached, capped 10-question dev runner as the CLI."""
    if not request.config.getoption("--run-live-smoke"):
        pytest.skip("Paid smoke requires --run-live-smoke and interactive confirmation")
    from app.config import load_settings
    load_settings()
    if not os.getenv("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY is absent")
    from app.evaluation.runner import main
    main(["--live", "--limit", "10", "--mode", "corrective", "--max-cost",
          os.getenv("LIVE_SMOKE_MAX_COST", "0.15")])
