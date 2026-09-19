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

    def diagnostics(self):
        self.checked += 1
        return {'executable': '/synthetic/official-codex', 'version': 'test-only',
                'codex_home': '/synthetic/private-codex-home', 'model': 'gpt-6-astra', 'effort': 'medium',
                'auth': self.auth, 'boundary_verified': True, 'ready': self.auth == 'chatgpt' and self.ready,
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
