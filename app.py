"""Study-with-AI: five local Streamlit screens, using one guarded Codex provider."""

import time
import uuid
from dataclasses import asdict
from datetime import datetime
from zoneinfo import ZoneInfo

import streamlit as st

from src.config import CACHE_DIR, DATA_DIR, USER_DATA_DIR
from src.progress import commit_learning_event
from src.runtime import create_runtime
from src.views.common import scope_key
from src.views.design import apply_design
from src.views.learning_profile import render_profile
from src.views.navigation import apply_navigation

get_runtime = st.cache_resource(create_runtime)
MODES = ["Dashboard", "RAG", "Feynman Drill", "Curriculum", "Library"]


@st.fragment(run_every=1)
def render_pomodoro_timer() -> None:
    st.markdown("### 🍅 集中トラッカー")
    started = st.session_state.get("pomodoro_start")
    if not started:
        if st.button("25分集中スタート", key="pomo_start"):
            st.session_state["pomodoro_start"] = time.time()
            st.session_state["pomodoro_id"] = uuid.uuid4().hex
            st.rerun()
        return
    elapsed = max(0, int(time.time() - started))
    st.info(f"{elapsed // 60:02d}:{elapsed % 60:02d} / 25:00")
    if elapsed >= 1500:
        commit_learning_event(None, "pomodoro:" + st.session_state["pomodoro_id"], exp_amount=20, pomodoro_minutes=25)
        st.session_state["pomodoro_start"] = None
        st.success("25分達成。20 EXPを記録しました。")
        st.rerun()
    if st.button("中断（記録なし）", key="pomo_cancel"):
        st.session_state["pomodoro_start"] = None
        st.rerun()


def main() -> None:
    st.set_page_config(page_title="Study-with-AI", page_icon=":material/menu_book:", layout="wide", initial_sidebar_state="expanded")
    apply_design()
    runtime = get_runtime(str(DATA_DIR), str(USER_DATA_DIR), str(CACHE_DIR))
    subjects = runtime.retriever.discover_subjects()
    apply_navigation(subjects)
    with st.sidebar:
        st.title("Study-with-AI")
        st.caption("あなたの教材から、あなたの学びへ。")
        labels = {"Dashboard": "今日の学び", "Curriculum": "コース・授業", "RAG": "内容を相談", "Feynman Drill": "テスト・復習", "Library": "教材ライブラリ"}
        mode = st.radio("画面", MODES, key="mode", format_func=lambda value: labels[value])
        subject = st.selectbox(
            "科目", [""] + subjects, format_func=lambda s: s or "教材未登録 / 未選択", key="selected_subject"
        )
        if subject:
            registry = scope_key(subject)
            sessions = runtime.store.get(registry, "sessions", [])
            if not sessions:
                sessions = runtime.store.append_session(registry, uuid.uuid4().hex)
            if st.button("新しい学習セッション"):
                sessions = runtime.store.append_session(registry, uuid.uuid4().hex)
                st.session_state["study_session"] = sessions[-1]
                st.rerun()
            # A previous subject's widget value is deliberately not reused.
            if st.session_state.get("study_session") not in sessions:
                st.session_state["study_session"] = sessions[-1]
            st.selectbox(
                "学習セッション", sessions, format_func=lambda value: f"セッション {value[:8]}", key="study_session"
            )
        st.divider()
        with st.expander("説明と検索の詳細"):
            audience = st.selectbox("ターゲット層", ["初心者向け (Beginner)", "専門家向け (Expert)"])
            length = st.selectbox("回答の長さ", ["簡潔 (Concise)", "普通 (Normal)", "長め・詳細 (Detailed)"], index=1)
            tutor_style = st.selectbox(
                "チュータースタイル", ["標準（理論と具体例）", "直感・具体例重視", "厳密・数式重視", "ソクラテス・スパルタ"]
            )
            require_math = st.toggle("計算・数式導出モード")
            top_k = st.slider("検索チャンク数", 1, 10, 5)
        render_pomodoro_timer()
        st.caption(f"表示時刻: {datetime.now(ZoneInfo('Asia/Tokyo')).strftime('%Y-%m-%d %H:%M')} Asia/Tokyo")
        if st.button("生成ジョブを停止して保存"):
            runtime.jobs.shutdown()
            st.success("このアプリのジョブを停止しました。サーバー終了は起動ターミナルでCtrl+C。")
            get_runtime.clear()
            st.stop()
    st.caption("GPT-6 Astra · Medium  /  PDFから学ぶ、あなた専用の学習室")
    profile = render_profile(runtime, subject)
    st.session_state["learning_options"] = asdict(profile) | {
        "audience": audience, "length": length, "tutor_style": tutor_style,
        "require_math": require_math, "top_k": top_k,
    }
    with st.expander("接続状態・設定・診断"):
        st.caption("生成時は必要な教材抜粋・会話・答案が公式Codex経由で送信され、ChatGPT契約の利用枠を使います。検索はローカルで動きます。Resetは自動消費しません。")
        st.write(
            {"model": "gpt-6-astra", "reasoning_effort": "medium", "generation": "公式Codex CLI / ChatGPTログイン"}
        )
        st.json(runtime.retriever.diagnostics(subject or None))
        st.json(runtime.jobs.list_jobs(limit=10))
        if st.button("Codexの版・認証・実行境界を診断（生成なし）"):
            st.session_state["codex_diagnostics"] = runtime.provider.diagnostics()
        if st.session_state.get("codex_diagnostics"):
            st.json(st.session_state["codex_diagnostics"])
        st.caption(
            "教材未登録・ローカルモデル未取得・Codex未認証は別々の状態です。認証や境界の問題は生成だけを停止します。"
        )
    try:
        if mode == "Dashboard":
            from src.views.view_dashboard import render_dashboard

            render_dashboard(runtime)
        elif mode == "Library":
            from src.views.view_library import render_library

            render_library(runtime)
        elif mode == "Curriculum":
            from src.views.view_curriculum import render_curriculum_mode

            render_curriculum_mode(runtime)
        elif not subject:
            st.info("Libraryに教材を登録して科目を選んでください。Dashboardと履歴は教材なしでも利用できます。")
        elif mode == "RAG":
            from src.views.view_rag import render_rag_mode

            render_rag_mode(runtime)
        else:
            from src.views.view_exam import render_exam_mode

            render_exam_mode(runtime)
    except (ValueError, RuntimeError, OSError) as exc:
        st.error(f"処理を停止しました: {exc}")
        st.caption("失敗した結果から進捗やEXPを更新しません。保存先・教材・診断を確認してください。")


if __name__ == "__main__":
    main()
