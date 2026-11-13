"""Cached catalog-only index resources, initialized after a question is submitted."""

from pathlib import Path

import streamlit as st

from app.observability.startup import startup_step
from app.retrieval.chunks import Chunk, chunk_catalog
from app.semantic.loader import load_catalog
from app.semantic.models import Catalog


@st.cache_resource(show_spinner=False)
def load_catalog_index(database: str, database_version: int, catalog_version: int) -> tuple[Catalog,list[Chunk]]:
    """Cache validated catalog chunks, invalidating on warehouse/catalog file changes."""
    startup_step("Loading and validating catalog")
    catalog = load_catalog(database=Path(database))
    startup_step("Building catalog retrieval index")
    chunks = chunk_catalog(catalog)
    startup_step("Catalog retrieval index ready")
    return catalog,chunks
