"""Material management works without any generation authentication."""

from pathlib import Path

import streamlit as st

from src.config import DATA_DIR
from src.materials import list_materials, save_pdf
from src.runtime import Runtime


def render_library(runtime: Runtime) -> None:
    st.title("📚 知識の書庫 (Library)")
    st.caption("教材PDFとローカル検索を管理します。教材はCodexへ自動送信されません。")
    subjects = runtime.retriever.discover_subjects()
    if not subjects:
        st.info("教材未登録です。カテゴリと科目を指定してPDFを登録してください。")
    for subject in subjects:
        with st.expander(subject):
            files = list_materials(Path(DATA_DIR), subject)
            for file in files:
                st.write(f"{file['path']} · {file['bytes'] / 1024:.1f} KB")
            st.json(runtime.retriever.diagnostics(subject))
            if st.button("ローカル索引を構築・更新", key="index_" + subject):
                result = runtime.retriever.index(subject)
                if result["mode"] == "hybrid":
                    st.success("ローカルEmbedding + BM25の索引を確認しました。")
                else:
                    st.info("BM25検索を利用できます。意味検索は無効です（モデル未取得・読込失敗など）。")
                st.json(result)
    st.subheader("PDFを登録")
    target = st.text_input("登録先（カテゴリ/科目）", placeholder="Mathematics/線形代数", key="upload_subject")
    uploaded_files = st.file_uploader("教材PDF（同名ファイルを上書きしません）", type=["pdf"], accept_multiple_files=True)
    if st.button("教材を保存", disabled=not uploaded_files or not target.strip()):
        for uploaded_file in uploaded_files:
            save_pdf(Path(DATA_DIR), target.strip(), uploaded_file.name, uploaded_file.getvalue())
        st.success("教材を保存しました。科目を選んで索引を構築できます。")
        st.rerun()
    st.caption(
        "旧APIベクトルは保持し、新しい索引はcache/local-retrieval-v2へ保存します。モデル取得はREADMEの明示コマンドで行います。"
    )
