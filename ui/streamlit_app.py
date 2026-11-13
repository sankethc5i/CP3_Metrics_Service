"""Streamlit question-to-answer UI with retrieval and trace inspection."""

from typing import Any


def main() -> None:
    """Run a configured governed query and display its complete response contract."""
    import streamlit as st

    st.set_page_config(page_title="Natural-Language Metrics Service",layout="wide")
    st.title("Natural-Language Metrics Service")
    try:
        _render(st)
    except Exception:
        # Never display exception strings, configuration reprs, or traceback details.
        print("[metrics startup] UI initialization/rendering failed; showing safe error",flush=True)
        st.error("The app could not initialize or display this result. Check the startup steps in the terminal and restart the app.")


def _render(st: Any) -> None:
    """Render controls before initializing the catalog, embedder or API client."""
    from pathlib import Path
    import sys

    # Direct script launch may put ui/ rather than the repository root on sys.path.
    root = str(Path(__file__).resolve().parents[1])
    if root not in sys.path:
        sys.path.insert(0,root)
    from app.observability.startup import startup_step

    startup_step("Rendering question controls")
    question = st.text_area("Question",placeholder="What was net revenue by category last month?",max_chars=4000)
    status = st.empty()
    status.info("Loading configuration…")
    settings = None
    try:
        startup_step("Loading configuration from environment and local .env")
        with st.spinner("Loading configuration…"):
            from app.config import AS_OF_DATE, load_settings
            settings = load_settings()
        startup_step("Configuration ready")
    except Exception:
        startup_step("Configuration failed; showing safe error")
        status.error("Configuration could not be loaded. Check RAG_MODE, EMBEDDING_PROVIDER, OPENAI_EMBEDDING_MODEL and SQLITE_PATH in .env. Blank values use defaults.")
    modes = ["lookup","naive","hybrid","hybrid_rerank","corrective"]
    mode = st.sidebar.selectbox("RAG_MODE",modes,index=modes.index(settings.rag_mode) if settings else 2)
    st.sidebar.caption("lookup: keywords · naive: dense · hybrid: RRF fusion")
    st.sidebar.caption("hybrid_rerank: local cross-encoder · corrective: graded, bounded local correction")
    submitted = st.button("Ask",type="primary",disabled=settings is None)
    if settings is None:
        return
    st.sidebar.caption(f"Embeddings: {settings.embedding_provider} · {settings.embedding_model}")
    st.sidebar.write("Relative dates use",AS_OF_DATE.isoformat())
    status.info("Ready. Enter a question and select Ask. The local model loads only when needed.")
    startup_step("UI ready; model/index/network work deferred until Ask")
    if submitted:
        from app.abuse import admit_request
        if not admit_request(st.session_state.setdefault("request_times",[]),
                             settings.session_rate_limit,settings.session_rate_window_seconds):
            status.error("Too many requests in this session. Please wait before trying again.")
            return
        status.info("Loading catalog and retrieval resources. First local-model use may download weights.")
        with st.spinner("Loading retrieval resources and answering… First local-model use may download weights."):
            try:
                startup_step("Initializing query service")
                from app.service import create_service
                service = create_service(settings.model_copy(update={"rag_mode":mode}))
                startup_step("Running retrieval and governed query pipeline")
                st.session_state["response"] = service.ask(question).model_dump(mode="json")
                startup_step("Request complete")
                status.empty()
            except Exception:
                startup_step("Query initialization failed; showing safe error")
                status.error("The query service could not be loaded. Check SQLITE_PATH, the catalog, EMBEDDING_PROVIDER and OPENAI_EMBEDDING_MODEL. No provider was substituted.")
                st.session_state.pop("response",None)
    response = st.session_state.get("response")
    if response is None:
        st.caption("Try net revenue, order lines, conversion rate, or average order value.")
        return
    left,right = st.columns(2)
    left.metric("Outcome",response["outcome"])
    right.metric("Latency",f"{response['latency_ms']:.0f} ms")
    if response["outcome"] == "refuse":
        st.error(response["text"])
    else:
        st.write(response["text"])
    st.caption("Trace ID: "+response["trace_id"])
    st.subheader("Value")
    if response["rows"]:
        st.dataframe(response["rows"],hide_index=True,use_container_width=True)
    else:
        st.write(response["value"])
    if response["options"]:
        st.write("Clarification options:",response["options"])
    st.subheader("Metric definition")
    st.write(response["metric_definition"] or "No metric selected.")
    with st.expander("SQL and bound parameters"):
        st.code(response["sql"] or "No SQL compiled.",language="sql")
        st.json(response["parameters"])
    with st.expander("Retrieved catalog chunks and scores"):
        for hit in response["retrieved"]:
            st.write(hit["chunk"]["id"],"—",hit["score"])
            st.json({"ranks":hit["ranks"],"scores":hit["scores"],"metadata":hit["chunk"]["metadata"]})
            st.text(hit["chunk"]["text"])
    with st.expander("Trace timeline"):
        if response.get("crag_path"):
            st.write("CRAG path: "+" → ".join(response["crag_path"]))
            st.json({"grades":response["evidence_grades"],"model_calls":response["model_calls"],
                "output_token_reservation":response["output_token_reservation"]})
        st.dataframe([{key:event.get(key) for key in ("step","status","started_ms","latency_ms")}
            for event in response["trace"]],hide_index=True,use_container_width=True)
        st.json(response["trace"])
    with st.expander("Structured response and deterministic calculations"):
        st.json(response)


if __name__ == "__main__":
    main()
