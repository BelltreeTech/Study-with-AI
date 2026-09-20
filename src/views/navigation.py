"""Defer navigation until before Streamlit instantiates its keyed widgets."""

import streamlit as st


def queue_navigation(mode: str, subject: str = '', course: str = '', topic: str = '') -> None:
    st.session_state['_study_navigation'] = {'mode': mode, 'subject': subject, 'course': course, 'topic': topic}


def apply_navigation(subjects: list[str]) -> None:
    request = st.session_state.pop('_study_navigation', None)
    if not request:
        return
    if request['mode'] in ('Dashboard', 'RAG', 'Feynman Drill', 'Curriculum', 'Library'):
        st.session_state['mode'] = request['mode']
    subject = request.get('subject')
    if subject in subjects:
        st.session_state['selected_subject'] = subject
        if request.get('course'):
            st.session_state['course_selector_' + subject] = request['course']
    if request.get('topic'):
        st.session_state['exam_topic'] = request['topic']
