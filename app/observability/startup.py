"""Fixed startup-stage logging without settings, exception text or credentials."""

import logging
import sys

LOGGER = logging.getLogger("metrics_service.startup")
if not LOGGER.handlers:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("[metrics startup] %(message)s"))
    LOGGER.addHandler(handler)
LOGGER.setLevel(logging.INFO)
LOGGER.propagate = False


def startup_step(message: str) -> None:
    """Log an application-authored stage message; never pass user/config values."""
    LOGGER.info(message)
