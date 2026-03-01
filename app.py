"""
RAGシステム Streamlit Webアプリケーション。

data/ ディレクトリ内のPDFを選択し、チャットインターフェースで質問応答を行う。
バックエンドには既存の src/ モジュール群（NumPyベースのベクトル検索）を使用。

本ファイルはルーティング（画面遷移）と全体設定のみを担当する司令塔。
各画面の描画ロジックは src/views/ 配下に分割されている。
"""

import streamlit as st
from pathlib import Path

from src.core.rag_core import RAGCore
from src.core.ai_tutor import AITutor
from src.views.view_rag import render_rag_mode
from src.views.view_curriculum import render_curriculum_mode
from src.views.view_exam import render_exam_mode


# PDFデータディレクトリ
k_dataDir = Path("data")


def get_available_subjects(base_path: str = "data") -> list[str]:
    """data/配下のサブフォルダ名（科目名）のリストを返す。"""
    base: Path = Path(base_path)
    if not base.exists():
        return []
    return sorted(
        entry.name
        for entry in base.iterdir()
        if entry.is_dir() and any(entry.glob("*.pdf"))
    )


def _build_components(subject: str) -> tuple[RAGCore, AITutor]:
    """
    指定された科目のRAGCoreとAITutorを構築（またはキャッシュから復元）する。

    セッションステートに保持し、科目が変わった場合のみ再構築する。

    Returns:
        (RAGCore, AITutor) のタプル
    """
    if (
        "rag_core" in st.session_state
        and "ai_tutor" in st.session_state
        and st.session_state.get("pipeline_key") == subject
    ):
        return st.session_state["rag_core"], st.session_state["ai_tutor"]

    with st.spinner(f"📚 {subject} のPDFを読み込み中... インデックスを構築しています"):
        rag_core = RAGCore(subject)

    # 読み込みスキップされたファイルがあればUIに警告
    if rag_core._skipped_files:
        skipped_list: str = "、".join(rag_core._skipped_files)
        st.warning(f"⚠️ 以下のファイルは読み込めませんでした: {skipped_list}")

    # AITutorを初期化し、検索インデックスを共有
    ai_tutor = AITutor(rag_core.get_client())
    ai_tutor.set_search_index(
        chunks=rag_core.get_chunks(),
        embeddings=rag_core.get_embeddings(),
        expand_query_fn=rag_core.expand_query,
    )

    st.session_state["rag_core"] = rag_core
    st.session_state["ai_tutor"] = ai_tutor
    st.session_state["pipeline_key"] = subject
    return rag_core, ai_tutor


def _render_lobby() -> None:
    """科目選択ロビー画面を表示する。"""
    st.title("📖 Study With AI")
    st.caption("学びたい科目を選んでください。各科目には専用のPDF教材が格納されています。")

    subjects: list[str] = get_available_subjects()

    if not subjects:
        st.error(
            "data/ ディレクトリに科目フォルダが見つかりません。\n\n"
            "以下のようなフォルダ構造でPDFを配置してください:\n\n"
            "```\n"
            "data/\n"
            "├── DeepLearning/\n"
            "│   └── deep_learning.pdf\n"
            "├── Math/\n"
            "│   └── linear_algebra.pdf\n"
            "└── Science/\n"
            "    └── physics.pdf\n"
            "```"
        )
        st.stop()

    st.subheader(f"📂 利用可能な科目（{len(subjects)} 件）")

    for subject_name in subjects:
        subject_dir: Path = Path("data") / subject_name
        pdf_count: int = len(list(subject_dir.glob("*.pdf")))
        pdf_names: list[str] = [p.name for p in sorted(subject_dir.glob("*.pdf"))]

        with st.container(border=True):
            col_info, col_action = st.columns([3, 1])

            with col_info:
                st.markdown(f"### 📚 {subject_name}")
                st.caption(f"教材: {pdf_count} 冊 — {', '.join(pdf_names)}")

            with col_action:
                if st.button(
                    "📚 学習を開始する",
                    key=f"select_{subject_name}",
                    type="primary",
                    use_container_width=True,
                ):
                    st.session_state["selected_subject"] = subject_name
                    st.rerun()


def main() -> None:
    """Streamlitアプリのメインエントリーポイント。"""
    # ページ設定
    st.set_page_config(
        page_title="まりによるRAG System - PDF質問応答",
        page_icon="📖",
        layout="wide",
    )

    # 科目未選択→ロビー画面
    if "selected_subject" not in st.session_state:
        st.session_state["selected_subject"] = ""

    selected_subject: str = st.session_state["selected_subject"]

    if not selected_subject:
        _render_lobby()
        return

    # ---- サイドバー ----
    with st.sidebar:
        # 科目名表示＋ロビーに戻るボタン
        st.markdown(f"### 📚 科目: **{selected_subject}**")
        if st.button("🏠 科目を選び直す（ロビーへ）", use_container_width=True):
            # セッションをクリアしてロビーに戻る
            st.session_state["selected_subject"] = ""
            st.session_state.pop("rag_core", None)
            st.session_state.pop("ai_tutor", None)
            st.session_state.pop("pipeline_key", None)
            st.rerun()

        st.divider()

        # デバッグモードトグル
        debug_mode: bool = st.toggle("🛠 テンソル透視鏡 (Debug Mode)", value=False)
        st.divider()

        # 検索パラメータ
        st.header("⚙️ 設定")
        top_k: int = st.slider("検索チャンク数 (top_k)", 1, 10, 5)

        st.divider()
        st.header("🎨 回答スタイル")
        style: str = st.selectbox(
            "ターゲット層",
            ["初心者向け (Beginner)", "専門家向け (Expert)"],
            index=0,
        )
        length: str = st.selectbox(
            "回答の長さ",
            ["簡潔 (Concise)", "普通 (Normal)", "長め・詳細 (Detailed)"],
            index=1,
        )

        st.divider()
        # モード選択
        st.header("🧭 モード")
        app_mode: str = st.radio(
            "モード選択",
            ["🔍 知識検索 (RAG)", "🎓 模擬試験 (Feynman Drill)", "🏫 カリキュラム学習 (Curriculum)"],
            index=0,
            label_visibility="collapsed",
        )

    # ---- コンポーネント初期化（科目名で構築） ----
    rag_core, ai_tutor = _build_components(selected_subject)

    # ================================================================
    # モード分岐（各Viewモジュールにルーティング）
    # ================================================================
    if app_mode == "🔍 知識検索 (RAG)":
        render_rag_mode(rag_core, debug_mode, top_k, style, length)
    elif app_mode == "🎓 模擬試験 (Feynman Drill)":
        render_exam_mode(ai_tutor)
    else:
        render_curriculum_mode(ai_tutor)


if __name__ == "__main__":
    main()
