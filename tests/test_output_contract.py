"""Content-free diagnostics with real parser and synthetic jobs only."""
import json

import pytest
from jsonschema import Draft202012Validator
from test_jobs import wait_job
from test_learning_v4 import plan

from src.codex_provider import CodexProvider, CodexSettings, ProviderError, codex_wire_schema
from src.jobs import JobManager
from src.output_contract import omitted_constraints, sanitize_diagnostic
from src.schemas import SCHEMAS


def parse(value, *, raw=False):
    events = [{'type': 'item.completed', 'item': {'type': 'agent_message',
               'text': value if raw else json.dumps(value)}}, {'type': 'turn.completed'}]
    return CodexProvider()._parse(('\n'.join(map(json.dumps, events)) + '\n').encode(), b'', 0, SCHEMAS['lecture_plan'])


@pytest.mark.parametrize('mutation,keyword,path', [
    (lambda p: p.update(title='日' * 121), 'maxLength', ['title']),
    (lambda p: p['sections'][0].update(title='日' * 81), 'maxLength', ['sections', 0, 'title']),
    (lambda p: p.update(objectives=['secret'] * 2), 'uniqueItems', ['objectives']),
    (lambda p: p.pop('title'), 'required', []),
    (lambda p: p.update(PRIVATE='secret'), 'additionalProperties', []),
])
def test_parser_reports_constraint_without_content(mutation, keyword, path):
    value = plan()
    mutation(value)
    if keyword in ('maxLength', 'uniqueItems'):
        assert Draft202012Validator(codex_wire_schema(SCHEMAS['lecture_plan'])).is_valid(value)
    with pytest.raises(ProviderError) as error:
        parse(value)
    detail = error.value.diagnostic
    assert detail['keyword'] == keyword and detail['path'] == path
    assert 'secret' not in json.dumps(detail) and 'PRIVATE' not in json.dumps(detail)
    assert '日' not in json.dumps(detail, ensure_ascii=False)


@pytest.mark.parametrize('raw', ['PRIVATE invalid', '```json\n{}\n```', '{"PRIVATE":'])
def test_bad_json_is_separate_and_private(raw):
    with pytest.raises(ProviderError) as error:
        parse(raw, raw=True)
    assert error.value.diagnostic['category'] == 'json_parse'
    assert 'PRIVATE' not in json.dumps(error.value.diagnostic)


def test_sanitizer_rejects_arbitrary_details():
    assert sanitize_diagnostic({'category': 'schema_validation', 'stage': [], 'keyword': [],
                                'path': ['SECRET', {'PRIVATE': 1}], 'actual': 'SECRET',
                                'message': 'SECRET'}) == {'category': 'schema_validation', 'path': ['?', '?']}


def test_provider_transmits_exact_omitted_constraints_and_still_bounds_input(monkeypatch):
    provider = CodexProvider()
    monkeypatch.setattr(provider, '_ensure_ready', lambda *a, **k: None)
    captured = []
    def execute(args, prompt, cwd, cancel):
        captured.append(prompt.decode())
        return b'{}\n', b'', 0
    monkeypatch.setattr(provider, '_execute', execute)
    with pytest.raises(ProviderError):
        provider.generate('SYNTHETIC TASK', SCHEMAS['lecture_plan'])
    assert all(rule in captured[0] for rule in omitted_constraints(SCHEMAS['lecture_plan']))
    assert '$.sections[].title: maxLength=80' in captured[0]
    assert '$.objectives: uniqueItems=True' in captured[0]
    tiny = CodexProvider(CodexSettings(max_input_bytes=30))
    with pytest.raises(ProviderError) as error:
        tiny.generate('ok', SCHEMAS['lecture_plan'])
    assert error.value.code == 'invalid_request'


def test_job_persists_safe_details_across_restart_without_retry(tmp_path):
    db = tmp_path / 'jobs.sqlite3'
    calls = []
    def worker(cancel):
        calls.append(1)
        try:
            parse({**plan(), 'title': 'PRIVATE' * 30})
        except ProviderError as exc:
            exc.diagnostic['stage'] = 'lecture_plan'
            raise
    with JobManager(db) as manager:
        job_id = manager.submit('lecture_batch', 'synthetic', {}, 'once', worker)
        job = wait_job(manager, job_id)
        assert job['state'] == 'failed' and job['result'] is None
        assert '講義設計' in job['error_message'] and '文字数' in job['error_message']
        assert job['diagnostic']['actual'] == 210
        assert 'PRIVATE' not in json.dumps(job)
        assert manager.submit('lecture_batch', 'synthetic', {}, 'once', worker) == job_id
    with JobManager(db) as manager:
        assert manager.get(job_id)['diagnostic'] == job['diagnostic']
    assert calls == [1]


def test_timeout_diagnostic_distinguishes_batch_from_section():
    from src.output_contract import diagnostic_message
    section = diagnostic_message({'category': 'timeout', 'stage': 'lecture_section',
                                  'limit': 180, 'path': ['sections', 4]})
    batch = diagnostic_message({'category': 'timeout', 'stage': 'lecture_batch', 'limit': 1800})
    assert '第5節' in section and '180秒' in section
    assert '章全体' in batch and '1800秒' in batch
