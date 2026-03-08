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
from src.state_manager import init_session_state
from src.views.view_rag import render_rag_mode
from src.views.view_curriculum import render_curriculum_mode
from src.views.view_exam import render_exam_mode


# PDFデータディレクトリ
k_dataDir = Path("data")


def get_grouped_subjects(base_path: str = "data") -> dict[str, list[str]]:
    """
    data/配下の2階層ディレクトリ構造を読み込み、カテゴリ別の科目辞書を返す。

    data/
    ├── Deep Learning/     ← 親カテゴリ
    │   ├── 深層学習/      ← 子科目（PDFを含む）
    │   │   └── book.pdf
    │   └── 機械学習/
    │       └── ml.pdf
    └── Mathematics/
        └── 線形代数/
            └── la.pdf

    Returns:
        {"Deep Learning": ["深層学習", "機械学習"], "Mathematics": ["線形代数"]}
    """
    base: Path = Path(base_path)
    if not base.exists():
        return {}

    grouped: dict[str, list[str]] = {}
    for category_dir in sorted(base.iterdir()):
        if not category_dir.is_dir():
            continue
        # 子ディレクトリのうち、PDFを含むものだけを科目として認識
        subjects: list[str] = sorted(
            child.name
            for child in category_dir.iterdir()
            if child.is_dir() and any(child.glob("*.pdf"))
        )
        if subjects:
            grouped[category_dir.name] = subjects

    return grouped


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

    grouped: dict[str, list[str]] = get_grouped_subjects()

    if not grouped:
        st.error(
            "data/ ディレクトリに科目フォルダが見つかりません。\n\n"
            "以下のような2階層フォルダ構造でPDFを配置してください:\n\n"
            "```\n"
            "data/\n"
            "├── Deep Learning/\n"
            "│   ├── 深層学習/\n"
            "│   │   └── deep_learning.pdf\n"
            "│   └── 機械学習/\n"
            "│       └── ml.pdf\n"
            "└── Mathematics/\n"
            "    └── 線形代数/\n"
            "        └── linear_algebra.pdf\n"
            "```"
        )
        st.stop()

    # 全科目数をカウント
    total_subjects: int = sum(len(subs) for subs in grouped.values())
    st.subheader(f"📂 利用可能な科目（{total_subjects} 件 / {len(grouped)} カテゴリ）")

    for category_name, subject_list in grouped.items():
        st.header(f"📁 {category_name}")

        for subject_name in subject_list:
            subject_path: str = f"{category_name}/{subject_name}"
            subject_dir: Path = Path("data") / category_name / subject_name
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
                        key=f"select_{subject_path}",
                        type="primary",
                        use_container_width=True,
                    ):
                        st.session_state["selected_subject"] = subject_path
                        st.rerun()


def main() -> None:
    """Streamlitアプリのメインエントリーポイント。"""
    # ページ設定
    st.set_page_config(
        page_title="まりによるRAG System - PDF質問応答",
        page_icon="📖",
        layout="wide",
    )

    # セッションステートの一括初期化
    init_session_state()

    selected_subject: str = st.session_state["selected_subject"]

    if not selected_subject:
        _render_lobby()
        return

    # ---- サイドバー ----
    with st.sidebar:
        # 科目名表示（"親カテゴリ/子科目" → "親カテゴリ > **子科目**" 形式）
        if "/" in selected_subject:
            parts: list[str] = selected_subject.split("/")
            display_label: str = f"{parts[0]} > **{parts[-1]}**"
        else:
            display_label = f"**{selected_subject}**"
        st.markdown(f"### 📚 科目: {display_label}")
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
        st.header("🗣️ チューターの解説スタイル")
        tutor_style: str = st.selectbox(
            "解説・対話の方針",
            [
                "🧑🏫 標準モード (理論と具体例のバランス)",
                "🎨 直感・具体例重視 (数式を減らし比喩を多用)",
                "🔬 厳密・数式重視 (定義と証明を妥協なく解説)",
                "👹 ソクラテス・スパルタ (答えを教えず問いで返す)",
            ],
            index=0,
            key="tutor_style_select",
        )
        st.session_state["tutor_style"] = tutor_style

        # 🧮 計算・数式導出モードのグローバルトグル
        require_math = st.toggle("🧮 計算・数式導出モード（途中式を重視）", value=False, key="require_math_toggle")
        st.session_state["require_math"] = require_math

        st.divider()
        # モード選択
        st.header("🧭 モード")
        app_mode: str = st.radio(
            "モード選択",
            ["📊 マイページ (Dashboard)", "🔍 知識検索 (RAG)", "🎓 模擬試験 (Feynman Drill)", "🏫 カリキュラム学習 (Curriculum)", "📚 知識の書庫 (Library)"],
            index=0,
            label_visibility="collapsed",
        )

    # --- ポモドーロ・タイマー (サイドバー常設) ---
    st.sidebar.divider()
    st.sidebar.markdown("### 🍅 集中トラッカー")

    import datetime
    if "pomodoro_start_time" not in st.session_state:
        st.session_state["pomodoro_start_time"] = None

    if st.session_state["pomodoro_start_time"] is None:
        if st.sidebar.button("▶️ 25分集中スタート", use_container_width=True):
            st.session_state["pomodoro_start_time"] = datetime.datetime.now()
            st.rerun()
    else:
        start_time = st.session_state["pomodoro_start_time"]
        elapsed_mins = (datetime.datetime.now() - start_time).total_seconds() / 60.0

        st.sidebar.info(f"🔥 集中モード実行中\n開始: {start_time.strftime('%H:%M')}")

        if st.sidebar.button("⏹️ セッション完了", type="primary", use_container_width=True):
            if elapsed_mins >= 25.0:
                from src.progress import add_exp, add_pomodoro_session
                add_pomodoro_session(25)
                # 科目名を「集中学習」としてEXPを追加
                add_exp("集中学習", 20)
                st.session_state["pomodoro_start_time"] = None
                st.sidebar.success("🎉 25分達成！ 20 EXP獲得！")
                st.balloons()
            else:
                st.sidebar.warning(f"⚠️ まだ {int(elapsed_mins)} 分です。25分以上の経過が必要です。")

        if st.sidebar.button("✖️ 中断する (記録なし)", use_container_width=True):
            st.session_state["pomodoro_start_time"] = None
            st.rerun()
    st.sidebar.divider()

    rag_core, ai_tutor = _build_components(selected_subject)

    # ================================================================
    # モード分岐（各Viewモジュールにルーティング）
    # ================================================================
    if app_mode == "📊 マイページ (Dashboard)":
        from src.views.view_dashboard import render_dashboard
        render_dashboard()
    elif app_mode == "📚 知識の書庫 (Library)":
        from src.views.view_library import render_library
        render_library()
    elif app_mode == "🔍 知識検索 (RAG)":
        render_rag_mode(rag_core, debug_mode, top_k, style, length)
    elif app_mode == "🎓 模擬試験 (Feynman Drill)":
        render_exam_mode(ai_tutor)
    else:
        render_curriculum_mode(ai_tutor)


if __name__ == "__main__":
    main()
