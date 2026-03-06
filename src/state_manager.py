"""
セッションステート管理モジュール。

アプリ全体で使用するst.session_stateの初期化を一元管理する。
各Viewが個別に初期化していたステートをここに集約し、
状態の全体像を把握しやすくする。
"""

import streamlit as st


def init_session_state() -> None:
    """
    アプリ全体のセッションステートを初期化する。

    すでに値が設定されているキーは上書きしない（冪等）。
    アプリ起動時にmain()から1回だけ呼び出す。
    """
    _defaults: dict = {
        # ============================================================
        # アプリ全体
        # ============================================================
        # 現在選択中の科目名（空文字 = ロビー画面）
        "selected_subject": "",
        # RAGCore / AITutor インスタンスキャッシュ
        "rag_core": None,
        "ai_tutor": None,
        "pipeline_key": "",

        # ============================================================
        # 知識検索モード (RAG)
        # ============================================================
        # チャット履歴
        "messages": [],

        # ============================================================
        # 模擬試験モード (Feynman Drill)
        # ============================================================
        # 出題中の問題テキスト
        "quiz_question": "",
        # 出題時の参照チャンク
        "quiz_ref_chunks": [],
        # 採点結果辞書
        "quiz_grading_result": None,
        # 選択中の科目（Feynman Drill内）
        "exam_subject": "",
        # 選択中の難易度
        "exam_difficulty": "Normal",
        # 別科目用AITutorキャッシュ
        "exam_ai_tutor_extra": None,

        # ============================================================
        # カリキュラム学習モード (Curriculum)
        # ============================================================
        # アクティブなコース名（空文字 = ダッシュボード）
        "active_course": "",
        # カリキュラム章リスト
        "curriculum": [],
        # 現在の章インデックス
        "current_chapter_index": 0,
        # 生成済み講義データ
        "current_lecture": None,
        # ソクラテス対話履歴
        "lecture_chat_history": [],
        # ソクラテス対話中の章インデックス
        "lecture_chat_chapter_idx": -1,

        # ============================================================
        # カリキュラム修了試験
        # ============================================================
        # 修了試験の問題テキスト
        "exam_question": "",
        # 修了試験の参照チャンク
        "exam_ref_chunks": [],
        # 修了試験の採点結果
        "exam_grading_result": None,
        # 修了試験の難易度
        "curriculum_exam_difficulty": "🟡 修士級（応用・分析）",
    }

    for key, default_value in _defaults.items():
        if key not in st.session_state:
            st.session_state[key] = default_value
