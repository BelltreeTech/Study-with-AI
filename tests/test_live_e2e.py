"""No live credentials/models: test the explicit live harness with a synthetic Provider."""
from __future__ import annotations

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
from test_learning import FakeProvider

from scripts import live_e2e
from scripts.live_e2e import OPERATIONS, Budget, HarnessHalted, LiveHarness, Workspace, atomic_json
from src.codex_provider import ProviderError
from src.embedder import LocalEmbedder
from src.retriever import LocalRetriever


class Phase2Fake(FakeProvider):
    def __init__(self, *, auth='chatgpt', ready=True, fail_operation=None):
        super().__init__()
        self.auth = auth
        self.ready = ready
        self.fail_operation = fail_operation
        self.probes = 0
        self.checked = 0
        self.probed_runtime = False
        self.catalog_listed = True

    def diagnostics(self):
        self.checked += 1
        return {'executable': '/synthetic/official-codex', 'version': 'test-only',
                'codex_home': '/synthetic/private-codex-home', 'model': 'gpt-6-astra', 'effort': 'medium',
                'auth': self.auth, 'boundary_verified': True, 'ready': self.auth == 'chatgpt' and self.ready,
                'model_status': 'listed' if self.catalog_listed else 'not_listed',
                'model_available': self.catalog_listed,
                'probe_ready': self.auth == 'chatgpt'}

    def probe_model(self, prompt, schema, cancel_event=None):
        self.probes += 1
        if self.fail_operation == 'probe':
            raise ProviderError('network_error', 'Synthetic probe failure; no network used.')
        self.probed_runtime = True
        return {'ok': True}

    def generate(self, prompt, schema, cancel_event=None):
        if not self.ready and not self.probed_runtime:
            raise ProviderError('model_unconfirmed', 'Synthetic fresh process needs a probe.')
        if 'items' in schema['properties'] and self.fail_operation == 'grade':
            raise ProviderError('rate_limited', 'Synthetic quota failure; no account used.')
        result = super().generate(prompt, schema, cancel_event)
        if 'items' in result:
            # Exactly one deliberately incorrect answer is penalized: 84 / 100.
            assert 'passively rereading while never attempting recall' in prompt
            result['items'][-1].update(points=0, reason='The synthetic answer confuses recall with passive rereading.',
                                       improvement='Recall first and separate the review sessions.')
            result['weaknesses'] = ['retrieval versus rereading']
        return result


@pytest.fixture
def harness(tmp_path, monkeypatch):
    monkeypatch.setattr(live_e2e, 'LocalRetriever', lambda data, cache: LocalRetriever(
        data, cache, embedder=LocalEmbedder(model_dir=tmp_path / 'intentionally-missing-model')))
    return LiveHarness(tmp_path, Phase2Fake())


def test_check_only_and_missing_explicit_opt_in_never_create_jobs(harness):
    report = harness.check()
    assert report['generation_jobs_started_by_check'] == 0
    assert not harness.workspace.root.exists()
    with pytest.raises(HarnessHalted, match='confirm-live'):
        harness.run(confirm_live=False)
    assert harness.provider.probes == 0 and harness.provider.calls == []


def test_auth_failure_starts_no_jobs_or_budget_reservations(harness):
    harness.provider.auth = 'unavailable'
    with pytest.raises(HarnessHalted) as failure:
        harness.run(confirm_live=True)
    assert failure.value.code == 'preflight_failed'
    assert not harness.workspace.jobs_path.exists()
    assert Budget(harness.workspace.ledger_path).rows() == []
    assert harness.provider.probes == 0 and harness.provider.calls == []


def test_seven_jobs_partial_wrong_grade_persist_and_restart_without_new_calls(harness):
    report = harness.run(confirm_live=True)
    assert report['reserved_jobs'] == report['submitted_jobs'] == 7
    assert report['technical_flow_completed']
    assert report['partial_wrong_grading']['total'] == 84
    assert report['partial_wrong_grading']['reduced_score_observed']
    assert report['synthetic_total_exp'] == 50 and report['chapter_completed']
    assert report['educational_quality'] == 'manual_review_required'
    assert report['cli_internal_attempts'] == report['server_inference_count'] == 'unknown'
    assert harness.provider.probes == 1 and len(harness.provider.calls) == 6
    # A fresh unauthenticated process restores already completed evidence only.
    restarted_provider = Phase2Fake(auth='unavailable')
    restarted = LiveHarness(harness.workspace.project_root, restarted_provider)
    again = restarted.run(confirm_live=True)
    assert again['reserved_jobs'] == 7 and again['synthetic_total_exp'] == 50
    assert restarted_provider.checked == restarted_provider.probes == 0
    assert restarted_provider.calls == []
    with sqlite3.connect(harness.workspace.state / 'progress.sqlite3') as db:
        raw = json.loads(db.execute('SELECT document FROM progress_state').fetchone()[0])
    assert len(raw['courses'][live_e2e.COURSE]['grade_history']) == 1


def test_first_error_halts_and_reserve_requires_explicit_evidence(harness):
    harness.provider.fail_operation = 'probe'
    with pytest.raises(HarnessHalted) as failure:
        harness.run(confirm_live=True)
    assert failure.value.code == 'network_error'
    assert len(Budget(harness.workspace.ledger_path).rows()) == 1
    assert harness.provider.probes == 1 and harness.provider.calls == []
    with pytest.raises(HarnessHalted) as repeat:
        harness.run(confirm_live=True)
    assert repeat.value.code == 'prior_failure'
    assert harness.provider.probes == 1
    harness.provider.fail_operation = None
    with pytest.raises(HarnessHalted) as no_evidence:
        harness.run(confirm_live=True, retry_operation='probe')
    assert no_evidence.value.code == 'retry_evidence_required'
    report = harness.run(confirm_live=True, retry_operation='probe',
                         retry_evidence='Synthetic failure removed after reviewing fake provider behavior and passing regression.')
    assert report['reserved_jobs'] == report['submitted_jobs'] == 8
    assert report['technical_flow_completed'] and report['synthetic_total_exp'] == 50
    assert harness.provider.probes == 2


def test_failed_seventh_job_can_resume_with_exactly_one_extra_job(harness):
    harness.provider.fail_operation = 'grade'
    with pytest.raises(HarnessHalted):
        harness.run(confirm_live=True)
    report = json.loads((harness.workspace.root / 'report.json').read_text())
    assert report['reserved_jobs'] == 7 and not report['chapter_completed']
    harness.provider.fail_operation = None
    report = harness.run(confirm_live=True, retry_operation='grade',
                         retry_evidence='Synthetic quota flag was cleared after test control verification; this is not a real account.')
    assert report['reserved_jobs'] == 8
    assert report['synthetic_total_exp'] == 50
    assert harness.provider.probes == 1 and len(harness.provider.calls) == 6


def test_atomic_budget_concurrent_same_operation_and_hard_maximum(tmp_path):
    workspace = Workspace(tmp_path)
    with workspace.lock():
        budget = Budget(workspace.ledger_path)
        def reserve_once(index):
            try:
                budget.reserve('probe', {'request_id': str(index)})
                return True
            except HarnessHalted:
                return False
        with ThreadPoolExecutor(max_workers=8) as workers:
            assert sum(workers.map(reserve_once, range(16))) == 1
        first = budget.latest('probe')
        budget.update(first, status='failed', error_code='synthetic')
        budget.reserve('probe', {'request_id': 'reserve'}, evidence='Synthetic failure cause has been reviewed and corrected.')
        for operation in OPERATIONS[1:]:
            budget.reserve(operation, {'request_id': operation})
        assert len(budget.rows()) == 8
        with pytest.raises(HarnessHalted) as limit:
            budget.reserve('grade', {'request_id': 'ninth'}, evidence='This request must never be admitted beyond eight jobs.')
        assert limit.value.code == 'budget_exhausted'
        assert len(Budget(workspace.ledger_path).rows()) == 8


def test_interrupted_reservation_is_not_automatically_launched(harness):
    with harness.workspace.lock():
        budget = Budget(harness.workspace.ledger_path)
        budget.reserve('probe', {'request_id': 'synthetic-interrupted', 'kind': 'probe'})
    with pytest.raises(HarnessHalted) as failure:
        harness.run(confirm_live=True)
    assert failure.value.code == 'prior_failure'
    assert harness.provider.probes == 0 and harness.provider.calls == []
    assert Budget(harness.workspace.ledger_path).latest('probe')['status'] == 'interrupted'


def test_existing_foreign_or_redirected_workspace_is_never_reinitialized(tmp_path):
    root = tmp_path / '.study-runtime' / 'phase2-live'
    root.mkdir(parents=True)
    private = root / 'keep.txt'
    private.write_text('Synthetic existing data, preserve me.')
    with pytest.raises(HarnessHalted) as failure, Workspace(tmp_path).lock():
        pass
    assert failure.value.code == 'wrong_owner'
    assert private.read_text() == 'Synthetic existing data, preserve me.'


def test_extra_material_rejected_before_any_generation(harness):
    with harness.workspace.lock():
        Budget(harness.workspace.ledger_path)
        harness.workspace.material()
        extra = harness.workspace.data / 'unexpected.pdf'
        extra.write_bytes(b'Synthetic unexpected file')
    with pytest.raises(HarnessHalted) as failure:
        harness.run(confirm_live=True)
    assert failure.value.code == 'unexpected_material'
    assert harness.provider.probes == 0 and harness.provider.calls == []


def test_quality_requires_manual_evidence_bound_to_exact_outputs(harness):
    report = harness.run(confirm_live=True)
    review = {'reviewer': 'Synthetic test reviewer', 'reviewed_at': '2026-09-19T20:00:00+09:00',
              'result_digest': 'stale', 'checks': {key: {'status': 'pass', 'evidence': 'Synthetic test evidence referencing page 1 and question q10.'}
                                                   for key in live_e2e.REVIEW_CHECKS}}
    atomic_json(harness.workspace.root / 'manual-review.json', review)
    assert harness.run(confirm_live=True)['educational_quality'] == 'manual_review_required'
    review['result_digest'] = report['review_result_digest']
    atomic_json(harness.workspace.root / 'manual-review.json', review)
    assert harness.run(confirm_live=True)['educational_quality'] == 'accepted_by_manual_evidence'
    # The test proves evidence gating only; its fake evidence is never a live-quality claim.
    assert harness.provider.probes == 1


def test_unknown_catalog_restart_requires_explicit_probe_and_counts_reserve(harness):
    harness.provider.ready = False
    # Synthetic recovery fixture: the process stopped after the first successful probe.
    with harness.workspace.lock():
        budget = Budget(harness.workspace.ledger_path)
        row = budget.reserve('probe', {'request_id': 'prior-probe', 'kind': 'probe'})
        budget.update(row, status='succeeded', job_id='synthetic-prior-probe', result='{"ok":true}')
    with pytest.raises(HarnessHalted) as blocked:
        harness.run(confirm_live=True)
    assert blocked.value.code == 'probe_resume_required'
    assert harness.provider.probes == 0 and harness.provider.calls == []
    report = harness.run(confirm_live=True, retry_operation='probe',
                         retry_evidence='Fresh runtime lost in-memory successful-probe evidence; same CLI and home verified again.')
    assert report['reserved_jobs'] == 8 and report['technical_flow_completed']
    assert report['synthetic_total_exp'] == 50
    assert harness.provider.probes == 1


def test_missing_ledger_never_resets_existing_budget(harness):
    harness.provider.auth = 'unavailable'
    with pytest.raises(HarnessHalted):
        harness.run(confirm_live=True)
    harness.workspace.ledger_path.unlink()  # Delete only this test's temporary synthetic fixture.
    with pytest.raises(HarnessHalted) as failure:
        harness.run(confirm_live=True)
    assert failure.value.code == 'ledger_missing'
    assert not harness.workspace.ledger_path.exists()
    assert harness.provider.probes == 0


RECOVERY_EVIDENCE = 'The two warning event hashes match official source; the exact disabled code-mode notice is now handled without enabling tools.'


def seed_known_warning_failures(harness):
    """Synthetic structural evidence only; neither old probe is made successful."""
    with harness.workspace.lock():
        budget = Budget(harness.workspace.ledger_path)
        budget.bind_runtime(harness.provider.diagnostics())
        for attempt in (1, 2):
            request = {'request_id': f'failed-probe-{attempt}', 'kind': 'probe',
                       'model': 'gpt-6-astra', 'effort': 'medium', 'schema': live_e2e.PROBE_SCHEMA}
            row = budget.reserve('probe', request, evidence=RECOVERY_EVIDENCE if attempt == 2 else None)
            budget.update(row, status='failed', error_code='process_error', job_id=f'synthetic-failed-{attempt}')
        metadata = {'stage': 'parse', 'error_code': 'process_error', 'returncode': 0,
                    'stdout_bytes': 945, 'stderr_bytes': 0,
                    'stderr_sha256': live_e2e.hashlib.sha256(b'').hexdigest(),
                    'events': live_e2e.RECOVERY_EVENTS, 'notices': live_e2e.RECOVERY_NOTICES,
                    'signatures': ['feature_warning']}
        atomic_json(harness.workspace.root / 'execution/probe-2.json', metadata)
    return metadata


def test_explicit_answer_check_finishes_six_operations_within_eight_total_and_restores(harness):
    seed_known_warning_failures(harness)
    result = harness.run(confirm_live=True, structured_check_with_answer=True,
                         recovery_evidence=RECOVERY_EVIDENCE)
    assert result['reserved_jobs'] == 8 and result['submitted_jobs'] == 8
    assert result['technical_flow_completed'] and result['chapter_completed']
    assert result['explicit_probe_succeeded'] is False
    assert result['structured_response_check'] == {'operation': 'answer', 'succeeded': True}
    assert result['failed_probes_reclassified'] is False
    assert result['structured_check_recovery']['evidence'] == RECOVERY_EVIDENCE
    probes = [row for row in Budget(harness.workspace.ledger_path).rows() if row['operation'] == 'probe']
    assert [row['status'] for row in probes] == ['failed', 'failed']
    assert harness.provider.probes == 0 and len(harness.provider.calls) == 6
    assert result['synthetic_total_exp'] == 50
    restarted_provider = Phase2Fake(auth='unavailable')
    restarted = LiveHarness(harness.workspace.project_root, restarted_provider)
    again = restarted.run(confirm_live=True)
    assert again['technical_flow_completed'] and again['reserved_jobs'] == 8
    assert again['synthetic_total_exp'] == 50
    assert restarted_provider.checked == restarted_provider.probes == 0
    assert restarted_provider.calls == []


def test_combined_check_cannot_be_implicit_or_have_missing_evidence(harness):
    seed_known_warning_failures(harness)
    with pytest.raises(HarnessHalted) as implicit:
        harness.run(confirm_live=True)
    assert implicit.value.code == 'prior_failure'
    with pytest.raises(HarnessHalted) as missing:
        harness.run(confirm_live=True, structured_check_with_answer=True)
    assert missing.value.code == 'recovery_evidence_required'
    assert len(Budget(harness.workspace.ledger_path).rows()) == 2
    assert harness.provider.probes == 0 and harness.provider.calls == []


@pytest.mark.parametrize('tamper', ['returncode', 'tool', 'notice', 'completion', 'final', 'unknown_event', 'stderr'])
def test_combined_check_requires_exact_known_warning_evidence(harness, tamper):
    metadata = seed_known_warning_failures(harness)
    # Independent deep copy: constants describe the audited incident, never a mutable fixture.
    metadata = json.loads(json.dumps(metadata))
    if tamper == 'returncode':
        metadata['returncode'] = 1
    elif tamper == 'tool':
        metadata['events']['item:command_execution'] = 1
    elif tamper == 'notice':
        metadata['notices'][1]['sha256'] = '0' * 64
    elif tamper == 'completion':
        metadata['events'].pop('turn.completed')
    elif tamper == 'final':
        metadata['events']['item:agent_message'] = 0
    elif tamper == 'unknown_event':
        metadata['events']['unknown_event'] = 1
    else:
        metadata['stderr_bytes'] = 1
    atomic_json(harness.workspace.root / 'execution/probe-2.json', metadata)
    with pytest.raises(HarnessHalted) as failure:
        harness.run(confirm_live=True, structured_check_with_answer=True,
                    recovery_evidence=RECOVERY_EVIDENCE)
    assert failure.value.code == 'recovery_proof_required'
    assert len(Budget(harness.workspace.ledger_path).rows()) == 2
    assert harness.provider.probes == 0 and harness.provider.calls == []


@pytest.mark.parametrize('ready,listed', [(False, True), (True, False)])
def test_combined_check_requires_normal_ready_and_catalog_listing(harness, ready, listed):
    seed_known_warning_failures(harness)
    harness.provider.ready = ready
    harness.provider.catalog_listed = listed
    with pytest.raises(HarnessHalted) as failure:
        harness.run(confirm_live=True, structured_check_with_answer=True,
                    recovery_evidence=RECOVERY_EVIDENCE)
    assert failure.value.code == 'recovery_catalog_required'
    assert harness.provider.probes == 0 and harness.provider.calls == []


def test_combined_check_failed_answer_is_not_a_structured_success_or_auto_retry(harness, monkeypatch):
    seed_known_warning_failures(harness)
    calls = []
    def fail(*args):
        calls.append('answer')
        raise ProviderError('rate_limited', 'Synthetic quota rejection')
    monkeypatch.setattr(harness.provider, 'generate', fail)
    with pytest.raises(HarnessHalted) as failure:
        harness.run(confirm_live=True, structured_check_with_answer=True,
                    recovery_evidence=RECOVERY_EVIDENCE)
    assert failure.value.code == 'rate_limited' and calls == ['answer']
    report = json.loads((harness.workspace.root / 'report.json').read_text())
    assert report['reserved_jobs'] == 3 and not report['technical_flow_completed']
    assert report['structured_response_check'] == {'operation': 'answer', 'succeeded': False}
    assert report['explicit_probe_succeeded'] is False
    with pytest.raises(HarnessHalted) as no_implicit_resume:
        harness.run(confirm_live=True)
    assert no_implicit_resume.value.code == 'recovery_opt_in_required'
    with pytest.raises(HarnessHalted) as no_auto_retry:
        harness.run(confirm_live=True, structured_check_with_answer=True,
                    recovery_evidence=RECOVERY_EVIDENCE)
    assert no_auto_retry.value.code == 'prior_failure' and calls == ['answer']


COURSE_RECOVERY_EVIDENCE = (
    'The recorded request was rejected with invalid_schema; uniqueItems is removed from the wire schema only, '
    'and the full original local validation remains covered by synthetic regressions.'
)


def seed_known_schema_failure(harness, monkeypatch):
    """Reproduce only the ledger and safe metadata, never any real CLI request."""
    seed_known_warning_failures(harness)
    def fail(*args):
        raise ProviderError('process_error', 'Synthetic schema rejection, matching the historical classification.')
    with monkeypatch.context() as patch:
        patch.setattr(harness.provider, 'generate', fail)
        with pytest.raises(HarnessHalted, match='answer'):
            harness.run(confirm_live=True, structured_check_with_answer=True, recovery_evidence=RECOVERY_EVIDENCE)
    metadata = {
        'stage': 'parse', 'returncode': 1, 'stdout_bytes': 1458, 'stderr_bytes': 0,
        'stderr_sha256': live_e2e.hashlib.sha256(b'').hexdigest(),
        'events': {'thread.started': 1, 'item.completed': 2, 'item:error': 2, 'turn.started': 1,
                   'error': 1, 'turn.failed': 1},
        'notices': json.loads(json.dumps(live_e2e.RECOVERY_NOTICES)) + [
            {'bytes': 376, 'sha256': '4a4236d883a7d15ea127aef25e7291ce623b2701394b22609b2846bc22fa5210'},
            {'bytes': 393, 'sha256': 'f957c207fc701f69a14bc7b031d11d44b95a7e5b06bda428f17721ac2b321200'},
        ],
        'signatures': ['invalid_schema', 'feature_warning', 'bad_request'], 'error_code': 'process_error',
    }
    atomic_json(harness.workspace.root / 'execution/answer-1.json', metadata)
    return metadata


def test_explicit_course_only_completes_five_jobs_but_never_reports_full_success(harness, monkeypatch):
    seed_known_schema_failure(harness, monkeypatch)
    before = Budget(harness.workspace.ledger_path).rows()
    result = harness.run(confirm_live=True, course_only_after_answer_failure=True,
                         recovery_evidence=COURSE_RECOVERY_EVIDENCE)
    assert result['reserved_jobs'] == result['submitted_jobs'] == 8
    assert result['technical_flow_completed'] is False
    assert result['course_flow_completed'] and result['chapter_completed']
    assert result['rag_answer_succeeded'] is False and result['explicit_probe_succeeded'] is False
    assert result['structured_response_check'] == {'operation': 'answer', 'succeeded': False}
    assert result['course_structured_response_check'] == {'operation': 'curriculum', 'succeeded': True}
    assert result['unverified_learning_operations'] == ['answer']
    assert result['failed_probes_reclassified'] is result['failed_answer_reclassified'] is False
    assert result['course_only_recovery']['evidence'] == COURSE_RECOVERY_EVIDENCE
    assert result['educational_quality'] == 'manual_review_required'
    assert harness.provider.probes == 0 and len(harness.provider.calls) == 5
    assert result['synthetic_total_exp'] == 50 and result['partial_wrong_grading']['total'] == 84
    assert Budget(harness.workspace.ledger_path).rows()[:3] == before

    restarted_provider = Phase2Fake(auth='unavailable')
    restarted = LiveHarness(harness.workspace.project_root, restarted_provider)
    again = restarted.run(confirm_live=True)
    assert again['technical_flow_completed'] is False and again['course_flow_completed']
    assert again['reserved_jobs'] == 8 and again['synthetic_total_exp'] == 50
    assert restarted_provider.checked == restarted_provider.probes == 0 and restarted_provider.calls == []
    with sqlite3.connect(harness.workspace.state / 'progress.sqlite3') as db:
        state = json.loads(db.execute('SELECT document FROM progress_state').fetchone()[0])
    course = state['courses'][live_e2e.COURSE]
    assert len(course['grade_history']) == 1
    curriculum = json.loads(Budget(harness.workspace.ledger_path).latest('curriculum')['result'])
    assert course['learning_options'] == curriculum['learning_options']
    assert course['material_revision'] == curriculum['material_revision']
    assert course['context_coverage'] == curriculum['context_coverage']


@pytest.mark.parametrize('flags,code', [
    ({}, 'recovery_opt_in_required'),
    ({'course_only_after_answer_failure': True}, 'recovery_evidence_required'),
    ({'course_only_after_answer_failure': True, 'structured_check_with_answer': True,
      'recovery_evidence': COURSE_RECOVERY_EVIDENCE}, 'conflicting_recovery'),
    ({'course_only_after_answer_failure': True, 'recovery_evidence': COURSE_RECOVERY_EVIDENCE,
      'retry_operation': 'answer', 'retry_evidence': COURSE_RECOVERY_EVIDENCE}, 'conflicting_recovery'),
])
def test_course_only_requires_specific_opt_in_and_cannot_retry_answer(harness, monkeypatch, flags, code):
    seed_known_schema_failure(harness, monkeypatch)
    with pytest.raises(HarnessHalted) as failure:
        harness.run(confirm_live=True, **flags)
    assert failure.value.code == code
    assert len(Budget(harness.workspace.ledger_path).rows()) == 3
    assert harness.provider.probes == 0 and harness.provider.calls == []


@pytest.mark.parametrize('tamper', ['returncode', 'signature', 'notice', 'tool', 'completion', 'missing'])
def test_course_only_refuses_changed_schema_failure_evidence(harness, monkeypatch, tamper):
    metadata = seed_known_schema_failure(harness, monkeypatch)
    path = harness.workspace.root / 'execution/answer-1.json'
    if tamper == 'missing':
        path.unlink()
    else:
        if tamper == 'returncode':
            metadata['returncode'] = 0
        elif tamper == 'signature':
            metadata['signatures'] = ['rate_limited']
        elif tamper == 'notice':
            metadata['notices'][-1]['sha256'] = '0' * 64
        elif tamper == 'tool':
            metadata['events']['item:command_execution'] = 1
        else:
            metadata['events']['turn.completed'] = 1
        atomic_json(path, metadata)
    with pytest.raises(HarnessHalted) as failure:
        harness.run(confirm_live=True, course_only_after_answer_failure=True,
                    recovery_evidence=COURSE_RECOVERY_EVIDENCE)
    assert failure.value.code == 'course_recovery_proof_required'
    assert len(Budget(harness.workspace.ledger_path).rows()) == 3 and harness.provider.calls == []


@pytest.mark.parametrize('ready,listed', [(False, True), (True, False)])
def test_course_only_still_requires_normal_ready_and_catalog(harness, monkeypatch, ready, listed):
    seed_known_schema_failure(harness, monkeypatch)
    harness.provider.ready, harness.provider.catalog_listed = ready, listed
    with pytest.raises(HarnessHalted) as failure:
        harness.run(confirm_live=True, course_only_after_answer_failure=True,
                    recovery_evidence=COURSE_RECOVERY_EVIDENCE)
    assert failure.value.code == 'recovery_catalog_required'
    assert len(Budget(harness.workspace.ledger_path).rows()) == 3 and harness.provider.calls == []


def test_course_only_stops_on_failure_without_implicit_or_explicit_extra_retry(harness, monkeypatch):
    seed_known_schema_failure(harness, monkeypatch)
    harness.provider.fail_operation = 'grade'
    with pytest.raises(HarnessHalted) as failure:
        harness.run(confirm_live=True, course_only_after_answer_failure=True,
                    recovery_evidence=COURSE_RECOVERY_EVIDENCE)
    assert failure.value.code == 'rate_limited'
    report = json.loads((harness.workspace.root / 'report.json').read_text())
    assert report['reserved_jobs'] == 8 and not report['course_flow_completed']
    assert not report['technical_flow_completed'] and not report['chapter_completed']
    assert len(harness.provider.calls) == 4
    with pytest.raises(HarnessHalted) as implicit:
        harness.run(confirm_live=True)
    assert implicit.value.code == 'recovery_opt_in_required'
    with pytest.raises(HarnessHalted) as repeated:
        harness.run(confirm_live=True, course_only_after_answer_failure=True,
                    recovery_evidence=COURSE_RECOVERY_EVIDENCE)
    assert repeated.value.code == 'prior_failure'
    with pytest.raises(HarnessHalted) as extra:
        harness.run(confirm_live=True, course_only_after_answer_failure=True,
                    recovery_evidence=COURSE_RECOVERY_EVIDENCE, retry_operation='grade',
                    retry_evidence=COURSE_RECOVERY_EVIDENCE)
    assert extra.value.code == 'conflicting_recovery'
    assert len(Budget(harness.workspace.ledger_path).rows()) == 8 and len(harness.provider.calls) == 4
