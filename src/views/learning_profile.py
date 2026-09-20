"""A durable, subject-scoped learning brief; never starts generation."""

from dataclasses import asdict

import streamlit as st

from src.config import LearningOptions
from src.runtime import Runtime
from src.views.common import scope_key

APPROACHES = ['体系的に理解', '例題を多く解く', '実践・プロジェクト', '試験に備える']


def load_profile(runtime: Runtime, subject: str) -> LearningOptions:
    default = runtime.store.get(scope_key('', view='learning-profile'), 'options', {}) if subject else {}
    saved = runtime.store.get(scope_key(subject, view='learning-profile'), 'options', default)
    try:
        return LearningOptions.from_saved(saved) if saved else LearningOptions()
    except (TypeError, ValueError):
        st.warning('保存された学び方を読み取れません。元の設定を保持しています。新しく保存するまで標準設定を使います。')
        return LearningOptions()


def render_profile(runtime: Runtime, subject: str) -> LearningOptions:
    profile = load_profile(runtime, subject)
    identity = scope_key(subject, view='learning-profile')
    with st.expander('あなたの学び方を設定', expanded=False):
        st.caption('科目ごとに保存します。新しいコースに引き継がれ、作成済みコースの授業方針は変わりません。')
        with st.form('profile_' + identity):
            goal = st.text_input('学習ゴール', value=profile.learning_goal, max_chars=1200,
                                 placeholder='例：統計の考え方を理解し、自分の研究データを分析したい')
            previous = st.text_input('すでに知っていること・苦手なこと', value=profile.prior_knowledge,
                                     max_chars=1200, placeholder='例：高校数学は学習済み。確率と記号の意味に自信がない')
            left, right = st.columns(2)
            approach = left.selectbox('学び方', APPROACHES, index=APPROACHES.index(profile.learning_approach))
            minutes = right.selectbox('1章のインプット時間の目安', [15, 25, 45, 60],
                                      index=[15, 25, 45, 60].index(profile.session_minutes), format_func=lambda n: f'{n}分')
            st.caption('講義を読み、解説付き例題やコードを追う時間です。練習・試験・復習は別時間です。')
            if profile.time_scope == 'legacy_total':
                st.caption('旧設定は練習を含む学習時間でした。保存するとインプット時間の目安へ変更します。')
            analogy = st.text_input('たとえ・例に使ってほしい分野', value=profile.analogy_domain, max_chars=300,
                                    placeholder='例：料理、野球、音楽、プログラミング、身近な買い物')
            if st.form_submit_button('学び方を保存', type='primary'):
                updated = LearningOptions(**(asdict(profile) | {
                    'time_scope': 'lecture_input', 'learning_goal': goal.strip(), 'prior_knowledge': previous.strip(),
                    'learning_approach': approach, 'session_minutes': minutes, 'analogy_domain': analogy.strip(),
                }))
                runtime.store.set(identity, 'options', asdict(updated))
                st.session_state['profile_saved'] = subject
                st.rerun()
    if st.session_state.pop('profile_saved', None) == subject:
        st.success('学び方を保存しました。新しいコースと内容相談に反映されます。')
    return profile
