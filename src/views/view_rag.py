"""Source-grounded conversation with durable drafts and local-only search."""

import streamlit as st

from src.runtime import Runtime
from src.views.common import options, render_pending, scope_key, show_sources, show_text, submit


def _save_query(runtime: Runtime, scope: str, key: str) -> None:
    runtime.store.set(scope, 'question_draft', st.session_state.get(key, ''))


def _save_context_mode(runtime: Runtime, scope: str, key: str) -> None:
    runtime.store.set(scope, 'context_mode', 'overview' if st.session_state.get(key) else 'search')


def _starter(runtime: Runtime, scope: str, key: str, text: str, overview_key: str, overview: bool) -> None:
    previous = st.session_state.get(key, '').strip()
    st.session_state[key] = previous + '\n' + text if previous else text
    _save_query(runtime, scope, key)
    if overview:
        st.session_state[overview_key] = True
        _save_context_mode(runtime, scope, overview_key)


def render_rag_mode(runtime: Runtime) -> None:
    st.title('教材について相談')
    st.caption('わからない言葉から、理解の確かめ方まで。教材のページを一緒に確認しながら考えます。')
    subject = st.session_state['selected_subject']
    scope = scope_key(subject, st.session_state['study_session'], view='rag')
    active = render_pending(runtime, scope)
    question_key = 'rag_query_' + scope
    overview_key = 'rag_overview_' + scope
    if question_key not in st.session_state:
        st.session_state[question_key] = runtime.store.get(scope, 'question_draft', '')
    if overview_key not in st.session_state:
        st.session_state[overview_key] = runtime.store.get(scope, 'context_mode', 'search') == 'overview'
    with st.container(border=True):
        query = st.text_input('検索語・質問', key=question_key, placeholder='例：この考え方を、料理にたとえるとどうなりますか？',
                              on_change=_save_query, args=(runtime, scope, question_key))
        cols = st.columns(3)
        for col, label, question in zip(cols,
            ['要点をつかむ', '例で説明してもらう', '理解を確かめる'],
            ['この教材で最初に理解すべき核心概念と、そのつながりを説明してください。',
             'このテーマを具体例で説明し、例が当てはまる範囲と限界も示してください。',
             '自分の言葉で説明して理解を確かめる問いを1つください。すぐに答えを示さず、考えるのを手伝ってください。'], strict=True):
            col.button(label, key=label + scope, disabled=active, on_click=_starter,
                       args=(runtime, scope, question_key, question, overview_key, label == '要点をつかむ'))
        st.caption('候補は入力欄に追加するだけです。質問を整えてから送信できます。')
        overview = st.checkbox('教材全体から代表的な抜粋を参照', key=overview_key,
                               on_change=_save_context_mode, args=(runtime, scope, overview_key))
        if overview:
            st.caption('この科目のPDFから代表的なページを選びます。全ページ・全概念の網羅を保証するものではありません。解除すると質問に一致する箇所を検索します。')
        context_mode = 'overview' if overview else 'search'
        left, right = st.columns(2)
        if left.button('教材に基づいて回答', disabled=active or not query.strip(), type='primary'):
            history = runtime.store.get(scope, 'history', [])
            submit(runtime, scope, 'answer', {'question': query, 'history': history[-20:], 'context_mode': context_mode})
        if right.button('ローカル検索（生成なし）', disabled=not query.strip()):
            with st.spinner('教材の該当箇所を探しています…'):
                if overview:
                    results = runtime.retriever.course_context(subject, query, max(options().top_k, 8))
                else:
                    results = runtime.retriever.search(subject, query, options().top_k)
            runtime.store.set(scope, 'search', results)
    search = runtime.store.get(scope, 'search', [])
    if search:
        st.caption('検索結果は教材の抜粋です。生成モデルは使用していません。')
        show_sources(search)
    with st.expander('出題傾向を調べる'):
        if st.button('出題傾向を分析', disabled=active or not query.strip()):
            submit(runtime, scope, 'trend', {'topic': query, 'context_mode': context_mode})
        trend = runtime.store.get(scope, 'trend')
        if trend:
            show_text(trend)
        st.caption('取得できた教材抜粋の範囲を分析します。資料全体の頻度統計ではありません。')
    st.subheader('会話履歴')
    history = runtime.store.get(scope, 'history', [])
    if not history:
        st.info('最初の質問から始めましょう。「どこがわからないか、まだわからない」でも大丈夫です。')
    for message in history:
        with st.chat_message(message['role']):
            if message.get('result'):
                show_text(message['result'])
            else:
                st.markdown(message['content'])
    if history:
        export = '\n\n'.join(('## 質問' if m['role'] == 'user' else '## 回答') + '\n\n' + m['content'] for m in history)
        st.download_button('この相談をノートに保存', export, file_name='learning-conversation.md')
    st.caption(f"検索状態: {runtime.retriever.diagnostics(subject).get('mode', 'not_indexed')}")
