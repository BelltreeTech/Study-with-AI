"""Chapter editions and explicit, checkpointed batch controls."""

import uuid
from dataclasses import replace

import streamlit as st

from src.config import LearningOptions
from src.lecture_batches import lecture_batch_scope
from src.runtime import Runtime
from src.views.common import render_markdown, render_pending, show_text, submit


def show_edition(lecture: dict) -> None:
    if lecture.get('format') == 'sections-v1':
        plan = lecture['plan']
        st.markdown('**この章の到達目標**')
        for objective in plan['objectives']:
            st.write('• ' + objective)
        titles = {item['section_id']: item['title'] for item in plan['sections']}
        for section in lecture['sections']:
            st.subheader(titles.get(section['section_id'], section['section_id']))
            show_text(section)
    elif 'markdown' in lecture:
        show_text(lecture)
    else:
        render_markdown(lecture.get('lecture_text', '').replace(r'\[', '$$').replace(r'\]', '$$')
                        .replace(r'\(', '$').replace(r'\)', '$'))


def edition_markdown(lecture: dict) -> str:
    if not lecture:
        return '（講義未生成）'
    parts = []
    plan = lecture.get('plan', {})
    titles = {s['section_id']: s['title'] for s in plan.get('sections', [])}
    if plan:
        parts += ['### 到達目標', '\n'.join('- ' + item for item in plan['objectives'])]
    for section in lecture.get('sections', [lecture]):
        if section.get('section_id') in titles:
            parts.append('### ' + titles[section['section_id']])
        parts.append(section.get('markdown', section.get('lecture_text', '')))
        if section.get('supplemental_markdown'):
            parts.extend(['### 一般的な補足（教材の引用ではありません）', section['supplemental_markdown']])
        for source in section.get('sources', section.get('source_chunks', [])):
            parts.append(f"- {source.get('source_id', '')}: {source['source_file']} p.{source['page_number']}")
    return '\n\n'.join(parts)


def batch_controls(runtime: Runtime, subject: str, course_id: str, index: int,
                   chapter: dict, teaching: LearningOptions) -> None:
    scope = lecture_batch_scope(subject, course_id, index)
    active = render_pending(runtime, scope)
    checkpoint = runtime.store.get(scope, 'lecture_batch', {})
    lecture = chapter.get('lecture_content') or {}
    partial = checkpoint and checkpoint.get('edition_id') != lecture.get('lecture_id')
    st.caption(f'1章のインプット時間の目安: {teaching.session_minutes}分。練習・試験・復習は別時間です。'
               '説明のつながりを優先するため、読む時間は前後します。')
    st.caption('初回は設計1回＋本文最大8節（最大9生成要求）。各要求180秒、1回の開始・再開全体30分。'
               '成功節を保存し、明示再開時は未完了分だけ追加で生成します。')
    if partial and not active:
        finished = checkpoint.get('status') == 'succeeded'
        if finished:
            st.info('本文はすべて保存済みです。下のボタンで講義へ反映します。追加の生成要求はありません。')
        else:
            st.info(f"作成途中: {len(checkpoint.get('sections', []))}節を保存済み。自動再開はしません。")
        for section in checkpoint.get('sections', []):
            with st.expander('作成途中 · ' + section.get('section_id', '節')):
                show_text(section)
        if st.button('保存済みの講義を反映' if finished else '未完了の節から再開'):
            submit(runtime, scope, 'lecture_batch', {
                'title': chapter['title'], 'description': chapter.get('description', ''),
                '_chapter_index': index, '_previous_lecture_id': lecture.get('lecture_id'),
                '_edition_id': checkpoint['edition_id'], '_batch_scope': scope,
            }, course_id=course_id, override_options=replace(teaching, time_scope='lecture_input'))
    label = ('この章の講義を生成' if not lecture else '新しい講義版を作る'
             if lecture.get('format') == 'sections-v1' else '新方式の講義を作る')
    if partial:
        st.caption('最初から新しい版を作る場合は、設計と本文に新たな生成要求を使います。保存済みの旧版は保持します。')
    if st.button(label, disabled=active):
        submit(runtime, scope, 'lecture_batch', {
            'title': chapter['title'], 'description': chapter.get('description', ''),
            '_chapter_index': index, '_previous_lecture_id': lecture.get('lecture_id'),
            '_edition_id': uuid.uuid4().hex, '_batch_scope': scope,
        }, course_id=course_id, override_options=replace(teaching, time_scope='lecture_input'))
