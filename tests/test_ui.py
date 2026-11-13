"""Streamlit UI smoke test with a real local service and mocked model output."""

from pathlib import Path
from unittest.mock import patch
import pytest

from streamlit.testing.v1 import AppTest

from app.config import ROOT, Settings
from tests.test_service import FakeModel, service


@pytest.mark.parametrize("entrypoint",["app.py","ui/streamlit_app.py"])
def test_question_to_rendered_ui(entrypoint: str, warehouse: Path, tmp_path: Path) -> None:
    """The question widget invokes the service and renders outcome/value/traces."""
    settings = Settings(database=warehouse,trace_dir=tmp_path/"traces")
    with patch("app.config.load_settings",return_value=settings), patch("app.service.create_service",side_effect=lambda _:service(warehouse,tmp_path,FakeModel())) as factory:
        app = AppTest.from_file(str(ROOT/entrypoint),default_timeout=20).run()
        assert not app.exception
        assert list(app.selectbox[0].options)==["lookup","naive","hybrid","hybrid_rerank","corrective"]
        assert app.selectbox[0].value=="hybrid"
        assert app.text_area[0].label=="Question"
        factory.assert_not_called()
        app.text_area[0].set_value("What is net revenue?")
        app.button[0].click().run()
        assert not app.exception
        assert app.metric[0].value=="answer"
        assert app.session_state["response"]["sql"]
        assert app.session_state["response"]["retrieved"]


def test_bad_configuration_keeps_controls_and_safe_error() -> None:
    """Invalid config never leaves the direct entry point blank or leaks error text."""
    with patch("app.config.load_settings",side_effect=ValueError("private-secret-in-error")), patch("app.service.create_service") as factory:
        app = AppTest.from_file(str(ROOT/"ui/streamlit_app.py")).run()
        assert not app.exception
        assert app.title[0].value=="Natural-Language Metrics Service"
        assert app.text_area[0].label=="Question" and app.selectbox[0].label=="RAG_MODE"
        assert app.button[0].disabled
        assert "EMBEDDING_PROVIDER" in app.error[0].value
        assert "private-secret" not in app.error[0].value
        factory.assert_not_called()


def test_startup_failure_is_visible_and_safe() -> None:
    """An index/service initialization error becomes st.error, never a traceback."""
    with patch("app.config.load_settings",return_value=Settings()), patch("app.service.create_service",side_effect=RuntimeError("private-secret-in-error")):
        app = AppTest.from_file(str(ROOT/"ui/streamlit_app.py")).run()
        app.text_area[0].set_value("What is net revenue?")
        app.button[0].click().run()
        assert not app.exception
        assert "SQLITE_PATH" in app.error[0].value
        assert "private-secret" not in app.error[0].value


def test_corrective_path_is_exposed(warehouse: Path, tmp_path: Path) -> None:
    """Corrective-mode UI submissions expose grading and decisions with stub models."""
    from tests.test_corrective import CorrectiveModel, corrective_app
    settings = Settings(database=warehouse,rag_mode="corrective")
    pipeline = corrective_app(warehouse,tmp_path,CorrectiveModel(["sufficient"]))
    with patch("app.config.load_settings",return_value=settings), patch("app.service.create_service",return_value=pipeline):
        app = AppTest.from_file(str(ROOT/"ui"/"streamlit_app.py"),default_timeout=20).run()
        assert app.selectbox[0].value=="corrective"
        app.text_area[0].set_value("Show net revenue.")
        app.button[0].click().run()
        assert not app.exception
        assert "grading" in app.session_state["response"]["crag_path"]
        assert app.session_state["response"]["evidence_grades"]
