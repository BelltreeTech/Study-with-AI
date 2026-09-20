"""Stored hints, learner drafts and formative feedback; no grading or XP."""

import streamlit as st

from src.lecture_context import select_edition_context
from src.views.common import render_markdown, render_pending, scope_key, show_sources, submit


def _save_draft(runtime, scope, key):
    runtime.store.set(scope, 'draft', st.session_state.get(key, ''))


def _save_review(runtime, scope, key):
    runtime.store.set(scope, 'review_candidate', st.session_state[key])


def _save_selection(runtime, scope, key):
    runtime.store.set(scope, 'selected_practice', st.session_state[key])


def render_practice(runtime, subject, session, course_id, index, lecture, teaching):
    st.subheader('理解を深める練習')
    st.caption('1セット3問。ヒント・解答の表示では生成しません。答案を送信したときだけフィードバックを生成します。'
               '合否・章の解放・EXPには影響しません。コードは自動実行しません。')
    sections = lecture.get('plan', {}).get('sections', [])
    names = {s['section_id']: s['title'] for s in sections}
    target = st.selectbox('練習する範囲', [''] + list(names), format_func=lambda key: names.get(key, '章全体'),
                          key='practice_target_' + lecture.get('lecture_id', 'legacy'))
    scope = scope_key(subject, session, course_id, str(index),
                      'practice:' + lecture.get('lecture_id', 'legacy') + ':' + target)
    active = render_pending(runtime, scope)
    current = runtime.store.get(scope, 'practice_set')
    if st.button('練習を3問作る', disabled=active):
        submit(runtime, scope, 'practice_set', {
            'topic': lecture.get('plan', {}).get('title', 'この章の理解'),
            **select_edition_context(lecture, target or None),
            'lecture_id': lecture.get('lecture_id', 'legacy'), 'chapter_index': index,
            **({'plan': lecture['plan']} if lecture.get('plan') else {}),
        }, course_id=course_id, override_options=teaching)
    choices = ([current['practice_id']] if current else []) + runtime.store.get(scope, 'practice_ids', [])
    if not choices:
        return
    selection_key = 'practice_set_' + scope
    observed_key = 'practice_latest_' + scope
    if current and st.session_state.get(observed_key, runtime.store.get(scope, 'last_seen_practice')) != current['practice_id']:
        st.session_state[selection_key] = current['practice_id']
        st.session_state[observed_key] = current['practice_id']
        runtime.store.set(scope, 'last_seen_practice', current['practice_id'])
        runtime.store.set(scope, 'selected_practice', current['practice_id'])
    elif selection_key not in st.session_state:
        saved_selection = runtime.store.get(scope, 'selected_practice')
        st.session_state[selection_key] = saved_selection if saved_selection in choices else choices[0]
    selected = st.selectbox('練習セット', list(dict.fromkeys(choices)),
                            format_func=lambda value: ('最新 · ' if current and value == current['practice_id'] else '履歴 · ') + value[:8],
                            key=selection_key, on_change=_save_selection, args=(runtime, scope, selection_key))
    practice = current if current and selected == current['practice_id'] else runtime.store.get(scope, 'practice_archive:' + selected)
    if not practice:
        return
    only_review = st.checkbox('このセットの復習候補だけ表示', key='review_filter_' + scope)
    visible = 0
    for number, question in enumerate(practice['questions'], 1):
        qscope = scope_key(subject, session, course_id, str(index),
                           'practice-feedback:' + lecture.get('lecture_id', 'legacy') + ':' + selected + ':' + question['id'])
        if only_review and not runtime.store.get(qscope, 'review_candidate', False):
            # A hidden question may still have a submitted job. Keep its result applicable.
            render_pending(runtime, qscope)
            continue
        visible += 1
        with st.container(border=True):
            kinds = {'concept': '自分の言葉で説明', 'application': '具体的に適用', 'calculation': '計算で確かめる', 'code': 'コードを理解する'}
            st.markdown(f"**問{number} · {kinds.get(question['kind'], '練習')}**")
            render_markdown(question['prompt'])
            st.caption('学習目標: ' + question['learning_objective'])
            hints_used = runtime.store.get(qscope, 'hints_used', 0)
            hints = runtime.store.get(qscope, 'hints_revealed', min(hints_used, len(question['hints'])))
            for hint in question['hints'][:hints]:
                st.info(hint)
            if st.button('次のヒントを見る', key='hint_' + qscope, disabled=hints >= len(question['hints'])):
                runtime.store.set(qscope, 'hints_used', hints_used + 1)
                runtime.store.set(qscope, 'hints_revealed', hints + 1)
                st.rerun()
            if st.button('解答・解説を開く', key='reveal_' + qscope):
                runtime.store.set(qscope, 'answer_revealed', True)
                st.rerun()
            if runtime.store.get(qscope, 'answer_revealed', False):
                render_markdown(question['answer'])
                render_markdown(question['explanation'])
                st.caption('確認基準: ' + ' / '.join(question['criteria']))
                show_sources([s for s in practice.get('sources', []) if s['source_id'] in question['source_ids']])
            pending = render_pending(runtime, qscope)
            key = 'practice_answer_' + qscope
            if key not in st.session_state:
                st.session_state[key] = runtime.store.get(qscope, 'draft', '')
            answer = st.text_area('自分の説明・答案', key=key, on_change=_save_draft,
                                  args=(runtime, qscope, key), max_chars=6000)
            if st.button('答案を送信してフィードバック', key='feedback_' + qscope, disabled=pending or not answer.strip()):
                submit(runtime, qscope, 'practice_feedback', {
                    'practice': practice, 'question_id': question['id'], 'answer': answer,
                    'lecture_id': lecture.get('lecture_id', 'legacy'), 'chapter_index': index,
                    'lecture_revision': lecture.get('material_revision'),
                }, course_id=course_id, override_options=teaching)
            submissions = runtime.store.get(qscope, 'submissions', [])
            for submission_index, item in enumerate(reversed(submissions)):
                label = ('最新のフィードバック' if submission_index == 0 else '以前のフィードバック') + f' · 提出{len(submissions) - submission_index}'
                with st.expander(label, expanded=submission_index == 0):
                    st.text(item['answer'])
                    feedback = item['feedback']
                    for field, title in [('strengths', 'できた点'), ('misconceptions', '誤解'), ('next_steps', '次に直す箇所')]:
                        st.markdown('**' + title + '**')
                        for text in feedback[field]:
                            st.write('• ' + text)
                    show_sources(feedback.get('sources', []))
            review = runtime.store.get(qscope, 'review_candidate', False)
            submissions = runtime.store.get(qscope, 'submissions', [])
            review_key = 'review_' + qscope + (submissions[-1]['job_id'] if submissions else '')
            st.checkbox('復習候補にする', value=review, key=review_key,
                        on_change=_save_review, args=(runtime, qscope, review_key))
            if st.button('もう一度解く（提出履歴は保持）', key='retry_' + qscope, disabled=pending):
                runtime.store.set(qscope, 'draft', '')
                runtime.store.set(qscope, 'answer_revealed', False)
                runtime.store.set(qscope, 'hints_revealed', 0)
                st.session_state.pop(key, None)
                st.rerun()

    if only_review and visible == 0:
        st.info('このセットに復習候補はありません。チェックを外すとすべての問題を表示します。')


def show_practice_history(runtime, subject, session, course_id, index, lecture):
    """Read-only access to old-edition practice; do not reveal unopened answers."""
    import json

    lecture_id = lecture.get('lecture_id', 'legacy')
    targets = [''] + [s['section_id'] for s in lecture.get('plan', {}).get('sections', [])]
    records = []
    for target in targets:
        scope = scope_key(subject, session, course_id, str(index), 'practice:' + lecture_id + ':' + target)
        current = runtime.store.get(scope, 'practice_set')
        sets = ([current] if current else []) + [runtime.store.get(scope, 'practice_archive:' + pid)
                                                for pid in runtime.store.get(scope, 'practice_ids', [])]
        for practice in sets:
            if not practice:
                continue
            for question in practice['questions']:
                qscope = scope_key(subject, session, course_id, str(index),
                                   'practice-feedback:' + lecture_id + ':' + practice['practice_id'] + ':' + question['id'])
                record = {'practice_id': practice['practice_id'], 'question': question['prompt'],
                          'draft': runtime.store.get(qscope, 'draft', ''),
                          'submissions': runtime.store.get(qscope, 'submissions', []),
                          'hints_used': runtime.store.get(qscope, 'hints_used', 0),
                          'review_candidate': runtime.store.get(qscope, 'review_candidate', False)}
                record['hints_revealed'] = runtime.store.get(qscope, 'hints_revealed', min(record['hints_used'], len(question['hints'])))
                if runtime.store.get(qscope, 'answer_revealed', False):
                    record.update(answer=question['answer'], explanation=question['explanation'])
                records.append(record)
    if records:
        with st.expander('旧版の練習・答案・フィードバック'):
            st.json(records)
            st.download_button('旧版の練習履歴を保存', json.dumps(records, ensure_ascii=False, indent=2),
                               'previous-practice.json')
