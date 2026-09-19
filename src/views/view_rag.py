"""Local retrieval remains usable independently from Codex generation."""

import streamlit as st

from src.runtime import Runtime
from src.views.common import options, render_pending, scope_key, show_sources, show_text, submit


def render_rag_mode(runtime: Runtime) -> None:
    st.title("🔍 知識検索 (RAG)")
    subject = st.session_state["selected_subject"]
    scope = scope_key(subject, st.session_state["study_session"], view="rag")
    active = render_pending(runtime, scope)
    query = st.text_input("検索語・質問", key="rag_query")
    if st.button("ローカル検索（生成なし）", disabled=not query.strip()):
        results = runtime.retriever.search(subject, query, options().top_k)
        runtime.store.set(scope, "search", results)
    search = runtime.store.get(scope, "search", [])
    if search:
        st.caption("検索結果は教材の抜粋です。生成モデルは使用していません。")
        show_sources(search)
    if st.button("教材に基づいて回答", disabled=active or not query.strip(), type="primary"):
        history = runtime.store.get(scope, "history", [])
        submit(
            runtime,
            scope,
            "answer",
            {"question": query, "history": history[-20:]},
        )
    if st.button("出題傾向を分析", disabled=active or not query.strip()):
        submit(runtime, scope, "trend", {"topic": query})
    trend = runtime.store.get(scope, "trend")
    if trend:
        with st.expander("出題傾向（取得できた抜粋の範囲）"):
            show_text(trend)
    st.subheader("会話履歴")
    for message in runtime.store.get(scope, "history", []):
        with st.chat_message(message["role"]):
            if message.get("result"):
                show_text(message["result"])
            else:
                st.markdown(message["content"])
    st.caption(f"検索状態: {runtime.retriever.diagnostics(subject).get('mode', 'not_indexed')}")
