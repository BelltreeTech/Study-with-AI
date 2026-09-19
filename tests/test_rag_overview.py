"""Explicit representative context works in local BM25 mode without an automatic fallback."""

import json

import pytest
from test_learning import FakeProvider
from test_ui import SUBJECT, assert_clean, button, finish_jobs, navigate, selectbox, text_content, text_input
from test_ui import ui_environment as ui_environment

from src.config import LearningOptions
from src.schemas import InvalidResult
from src.service import StudyService
from src.views.common import scope_key


class RecordingRetriever:
    def __init__(self):
        self.calls = []

    def revision(self, subject):
        return 'synthetic-revision'

    def search(self, subject, query, top_k=5):
        self.calls.append(('search', subject, query, top_k))
        return []

    def course_context(self, subject, query, top_k=8):
        self.calls.append(('overview', subject, query, top_k))
        return [{'source_id': f'S-{index}', 'source_file': 'synthetic.pdf', 'page_number': index + 1,
                 'chunk_id': str(index), 'text': 'Synthetic recall material. ' * 100,
                 'context_coverage': {'scope': 'representative_excerpts', 'selected_chunk_count': 12}}
                for index in range(12)]


def test_explicit_overview_uses_common_context_limits_and_real_coverage():
    retriever, provider = RecordingRetriever(), FakeProvider()
    service = StudyService(provider, retriever)
    request = service.prepare('answer', 'Synthetic/Study', 'session', {
        'question': 'Give a general overview.', 'context_mode': 'overview',
        'context_coverage': {'scope': 'caller-forged-all-pages'},
    }, LearningOptions(top_k=2))
    assert retriever.calls == [('overview', 'Synthetic/Study', 'Give a general overview.', 8)]
    assert 0 < len(request.sources) <= 10
    assert sum(len(source['text']) for source in request.sources) <= 10000
    assert max(len(source['text']) for source in request.sources) <= 1600
    coverage = request.payload['context_coverage']
    assert coverage['scope'] == 'representative_excerpts'
    assert coverage['provided_chunk_count'] == len(request.sources)
    assert coverage['provided_page_count'] == len(request.sources)
    assert coverage['provided_text_chars'] == sum(len(source['text']) for source in request.sources)
    result = service.execute(request)
    assert result['context_coverage'] == coverage
    assert 'caller-forged-all-pages' not in provider.calls[-1]
    assert '全ページ・全概念を網羅したとは述べず' in provider.calls[-1]


@pytest.mark.parametrize('mode', [None, '', 'automatic', 'overview; execute', True, ['overview'], {'mode': 'overview'}])
def test_context_mode_is_a_fixed_enum_before_any_retrieval(mode):
    retriever = RecordingRetriever()
    service = StudyService(FakeProvider(), retriever)
    with pytest.raises(ValueError, match='searchまたはoverview'):
        service.prepare('answer', 'Synthetic/Study', 'session', {'question': 'recall', 'context_mode': mode},
                        LearningOptions())
    assert retriever.calls == []


def test_regular_no_hit_search_does_not_silently_become_overview():
    retriever, provider = RecordingRetriever(), FakeProvider()
    service = StudyService(provider, retriever)
    with pytest.raises(InvalidResult, match='根拠を取得できません'):
        service.prepare('answer', 'Synthetic/Study', 'session', {'question': 'no match'}, LearningOptions())
    assert retriever.calls == [('search', 'Synthetic/Study', 'no match', 5)]
    assert provider.calls == []


def test_rag_overview_starter_can_search_and_answer_without_embeddings(ui_environment):
    app = ui_environment.app()
    selectbox(app, '科目').select(SUBJECT).run()
    navigate(app, 'RAG')
    button(app, '要点をつかむ').click().run()
    assert_clean(app)
    checkbox = next(item for item in app.checkbox if item.label == '教材全体から代表的な抜粋を参照')
    assert checkbox.value
    assert '全ページ・全概念の網羅を保証するものではありません' in text_content(app)
    assert ui_environment.provider.calls == []
    button(app, 'ローカル検索（生成なし）').click().run()
    assert_clean(app)
    assert 'Retrieval practice improves memory' in text_content(app)
    assert ui_environment.provider.calls == []
    button(app, '教材に基づいて回答').click().run()
    finish_jobs(app, ui_environment)
    assert len(ui_environment.provider.calls) == 1
    assert len(app.chat_message) == 2
    assert ui_environment.runtimes[-1].retriever.diagnostics(SUBJECT)['mode'] == 'bm25'
    data = json.loads(ui_environment.provider.calls[-1].split('BEGIN_UNTRUSTED_DATA_JSON\n')[1]
                      .split('\nEND_UNTRUSTED_DATA_JSON')[0])
    assert data['input']['context_mode'] == 'overview'
    assert data['input']['context_coverage']['scope'] == 'representative_excerpts'
    # The learner can return to ordinary retrieval. A miss stays a miss.
    next(item for item in app.checkbox if item.label == checkbox.label).uncheck().run()
    text_input(app, '検索語・質問').input('絶対に本文に無い合成キーワード').run()
    button(app, '教材に基づいて回答').click().run()
    assert not app.exception
    assert any('根拠を取得できません' in item.value for item in app.error)
    assert len(ui_environment.provider.calls) == 1
    assert len(ui_environment.runtimes[-1].jobs.list_jobs()) == 1


def test_overview_choice_is_scoped_to_session_and_survives_restart(ui_environment):
    app = ui_environment.app()
    selectbox(app, '科目').select(SUBJECT).run()
    navigate(app, 'RAG')
    button(app, '要点をつかむ').click().run()
    original_session = app.session_state['study_session']
    runtime = ui_environment.runtimes[-1]
    scope = scope_key(SUBJECT, original_session, view='rag')
    assert runtime.store.get(scope, 'context_mode') == 'overview'
    button(app, '新しい学習セッション').click().run()
    assert not next(item for item in app.checkbox if item.label == '教材全体から代表的な抜粋を参照').value
    selectbox(app, '学習セッション').select(original_session).run()
    assert next(item for item in app.checkbox if item.label == '教材全体から代表的な抜粋を参照').value
    ui_environment.shutdown()
    restarted = ui_environment.app()
    selectbox(restarted, '科目').select(SUBJECT).run()
    selectbox(restarted, '学習セッション').select(original_session).run()
    navigate(restarted, 'RAG')
    assert next(item for item in restarted.checkbox if item.label == '教材全体から代表的な抜粋を参照').value
    assert ui_environment.provider.calls == []
