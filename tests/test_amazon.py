"""Amazon candidate unions, complete audits, eligibility, and silent recovery."""
import json
from collections import Counter
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from threading import Barrier, Lock

import httpx
import pytest

from intern_alerts.classify import classify
from intern_alerts.config import Board, Config
from intern_alerts.main import run
from intern_alerts.dedup import SeenIndex
from intern_alerts.models import CHANNELS
from intern_alerts.normalize import normalize_url
from intern_alerts.sources import SourceError
from intern_alerts.sources import amazon
from intern_alerts.state import Record, State

BOARD = Board('amazon', 'amazon', 'Amazon')
NOW = datetime(2026, 10, 5, tzinfo=UTC)
JOB = json.loads((Path(__file__).parent / 'fixtures/amazon.json').read_text())


def job(job_id='123', group='alpha', **changes):
    return dict(dict(deepcopy(JOB), id_icims=job_id, business_category=group,
                job_path=f'/en/jobs/{job_id}/software-intern',
                title=f'Software Engineer Intern {job_id}', country_code='USA'), **changes)


class AmazonWeb:
    def __init__(self):
        self.jobs = [job(str(i), 'alpha' if i < 3 else 'beta') for i in range(5)]
        self.failure = None
        self.count_calls = 0
        self.offsets = []

    def handler(self, request):
        if request.url.host == 'simplify.test':
            return httpx.Response(200, json=[])
        query = request.url.params
        group = query.get('business_category[]')
        rows = [j for j in self.jobs if not group or j['business_category'] == group]
        offset, limit = int(query['offset']), int(query['result_limit'])
        if group:
            self.offsets.append((group, offset))
            if self.failure == 'http' and offset:
                return httpx.Response(503)
        else:
            self.count_calls += 1
        groups = Counter(j['business_category'] for j in self.jobs)
        countries = Counter(j['country_code'] for j in self.jobs)
        facets = {'business_category_facet': [{k: v} for k, v in groups.items()],
                  'normalized_country_code_facet': [{k: v} for k, v in countries.items()]}
        hits = min(len(rows), amazon.RESULT_CAP)
        selected = deepcopy(rows[offset:offset + limit])
        if group and offset and self.failure == 'short':
            selected = []
        if group and offset and self.failure == 'duplicate':
            selected = deepcopy(rows[:len(selected)])
        if group and self.failure == 'wrong_group':
            selected[0]['business_category'] = 'other'
        if group and self.failure == 'changed_page':
            hits += 1
        if group and self.failure == 'bad_detail':
            selected[0]['locations'] = ['{bad']
        if not group and self.failure == 'country_count':
            facets['normalized_country_code_facet'] = [{'USA': len(rows) + 1}]
        if not group and self.failure == 'changed_final' and self.count_calls > 1:
            facets['business_category_facet'][0]['alpha'] += 1
            facets['normalized_country_code_facet'][0]['USA'] += 1
            hits = min(len(rows) + 1, amazon.RESULT_CAP)
        error = 'upstream error' if self.failure == 'api_error' else None
        return httpx.Response(200, json={'error': error, 'hits': hits,
                                       'jobs': selected, 'facets': facets})

    def client(self):
        return httpx.Client(transport=httpx.MockTransport(self.handler))


@pytest.fixture(autouse=True)
def small_pages(monkeypatch):
    monkeypatch.setattr(amazon, 'PAGE_SIZE', 2)
    monkeypatch.setattr(amazon, 'RESULT_CAP', 5)


def test_scan_exceeds_global_cap_and_preserves_partition_order(monkeypatch):
    monkeypatch.setattr(amazon, 'RESULT_CAP', 4)
    web = AmazonWeb()
    with web.client() as client:
        postings = amazon.fetch_amazon_full_scan(client, BOARD)
    assert [p.job_id for p in postings] == ['0', '1', '2', '3', '4']
    assert set(web.offsets) == {('alpha', 0), ('alpha', 2), ('beta', 0)}
    assert web.count_calls == 2


@pytest.mark.parametrize('change', ['add_job', 'add_group', 'remove_group'])
def test_count_churn_refetches_only_changed_partitions(change):
    web = AmazonWeb()
    original = web.handler
    def handler(request):
        if not request.url.params.get('business_category[]') and web.count_calls == 1:
            if change == 'add_job':
                web.jobs.append(job('5', 'beta'))
            elif change == 'add_group':
                web.jobs.append(job('5', 'gamma'))
            else:
                web.jobs = [j for j in web.jobs if j['business_category'] != 'beta']
        return original(request)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        postings = amazon.fetch_amazon_full_scan(client, BOARD)
    assert [p.job_id for p in postings] == [j['id_icims'] for j in web.jobs]
    assert web.count_calls == 3
    assert web.offsets.count(('alpha', 0)) == 1
    assert web.offsets.count(('beta', 0)) == (2 if change == 'add_job' else 1)


def test_partition_changing_during_a_page_is_refetched_completely():
    web = AmazonWeb()
    original = web.handler
    def handler(request):
        query = request.url.params
        if query.get('business_category[]') == 'alpha' and query['offset'] == '2':
            if len(web.jobs) == 5:
                web.jobs.append(job('5', 'alpha'))
        return original(request)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        postings = amazon.fetch_amazon_full_scan(client, BOARD)
    assert [p.job_id for p in postings] == ['0', '1', '2', '5', '3', '4']
    assert web.count_calls == 3
    assert web.offsets.count(('alpha', 0)) == web.offsets.count(('alpha', 2)) == 2
    assert web.offsets.count(('beta', 0)) == 1


def test_country_churn_without_business_changes_rescans_every_partition():
    web = AmazonWeb()
    original = web.handler
    def handler(request):
        if not request.url.params.get('business_category[]') and web.count_calls == 1:
            web.jobs[-1]['country_code'] = 'CAN'
        return original(request)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert len(amazon.fetch_amazon_full_scan(client, BOARD)) == 5
    assert web.count_calls == 3
    assert all(web.offsets.count(pair) == 2 for pair in set(web.offsets))


def test_continuous_changes_exhaust_three_passes():
    web = AmazonWeb()
    original = web.handler
    def handler(request):
        if not request.url.params.get('business_category[]') and web.count_calls:
            web.jobs.append(job(str(len(web.jobs)), f'group-{web.count_calls}'))
        return original(request)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(SourceError, match='three passes'):
            amazon.fetch_amazon_full_scan(client, BOARD)
    assert web.count_calls == 4


def test_empty_non_list_facets_cannot_establish_an_empty_board():
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={
        'error': None, 'hits': 0, 'jobs': [],
        'facets': {name: {} for name in amazon.FACETS},
    }))) as client:
        with pytest.raises(SourceError, match='invalid facet list'):
            amazon.fetch_amazon_full_scan(client, BOARD)


def test_real_field_structure_asic_locations_and_date():
    p = amazon.parse_amazon(JOB, BOARD)
    assert p.job_id == '10517535'
    assert p.company == 'Amazon' and p.board_key == BOARD.key
    assert p.posted_at == datetime(2026, 8, 27, tzinfo=UTC)
    assert len(p.locations) == 3
    assert p.locations[0] == 'Austin, Texas, United States'
    assert p.degrees == ("Bachelor's", "Master's")
    assert classify(p).channels == {'hardware'}


@pytest.mark.parametrize('title,channels', [
    ('Business Developer Intern - 2027 - 12 Months', set()),
    ('Software Developer Intern', {'swe'}),
    ('Business Developer Intern, Software Engineering', {'swe'}),
])
def test_business_developer_is_not_a_software_signal(title, channels):
    assert classify(amazon.parse_amazon(job(title=title), BOARD)).channels == channels


@pytest.mark.parametrize('basic,preferred,eligible', [
    ('Currently enrolled in a PhD program.', '', False),
    ("Enrolled in a PhD or Master's degree.", '', False),
    ("Currently pursuing a Bachelor's or Master's degree.", '', True),
    ('Currently pursuing an Associate degree.', '', True),
    ('Experience developing software.', 'PhD degree preferred.', True),
    ('', '', True),
])
def test_only_required_qualifications_establish_degree(basic, preferred, eligible):
    p = amazon.parse_amazon(job(basic_qualifications=basic, preferred_qualifications=preferred), BOARD)
    assert classify(p).announce is eligible


@pytest.mark.parametrize('title', ['Software Engineer Intern (PhD)', 'High School Software Intern'])
def test_shared_title_exclusions(title):
    web = AmazonWeb()
    web.jobs = [job(title=title)]
    with web.client() as client:
        assert amazon.fetch_amazon_full_scan(client, BOARD) == []


@pytest.mark.parametrize('failure', ['http', 'short', 'duplicate', 'wrong_group', 'changed_page',
                                     'bad_detail', 'country_count', 'changed_final', 'api_error'])
def test_incomplete_or_untrusted_board_is_rejected(failure):
    web = AmazonWeb()
    web.failure = failure
    with web.client() as client, pytest.raises(SourceError, match='amazon:amazon'):
        amazon.fetch_amazon_full_scan(client, BOARD)


def test_alphanumeric_id_and_verified_url_aliases():
    p = amazon.parse_amazon(job('SF260123193'), BOARD)
    assert p.job_id == 'SF260123193'
    assert normalize_url(p.url) == 'https://amazon.jobs/en/jobs/SF260123193'
    assert normalize_url('http://amazon.jobs/en/jobs/123?utm_source=Simplify') == normalize_url(
        'https://www.amazon.jobs/en/jobs/123/old-title')
    assert normalize_url('https://account.amazon.jobs/jobs/123/apply') != normalize_url(
        'https://amazon.jobs/en/jobs/123')
    assert normalize_url('https://other.test/en/jobs/123/title').endswith('/title')
    historical = replace(Record.from_posting(p), job_id='simplify-uuid', title='old title',
                         url='https://amazon.jobs/en/jobs/SF260123193/old-title')
    assert SeenIndex([historical]).seen_by(p) == 'url'


@pytest.mark.parametrize('changes', [
    {'job_path': '/en/jobs/different/software-intern'}, {'id_icims': 'bad/id'},
    {'posted_date': 'Yesterday'}, {'locations': None}, {'locations': ['not JSON']},
    {'locations': [json.dumps({'city': 'Austin'})]}, {'basic_qualifications': None},
])
def test_required_metadata_is_not_fabricated(changes):
    with pytest.raises((ValueError, TypeError, KeyError)):
        amazon.parse_amazon(job(**changes), BOARD)


def test_all_locations_and_remote_country_rules():
    data = job(locations=[json.dumps({'city': 'Bengaluru', 'normalizedStateName': 'Karnataka',
                                     'normalizedCountryName': 'India', 'type': 'REMOTE'})])
    assert not classify(amazon.parse_amazon(data, BOARD)).announce
    data['locations'].append(json.dumps({'city': 'Toronto', 'normalizedStateName': 'Ontario',
                                        'normalizedCountryName': 'Canada', 'type': 'REMOTE'}))
    assert classify(amazon.parse_amazon(data, BOARD)).regions == {'Remote'}


def test_empty_board_requires_verified_zero_counts():
    web = AmazonWeb()
    web.jobs = []
    with web.client() as client:
        assert amazon.fetch_amazon_full_scan(client, BOARD) == []
    assert web.count_calls == 2


def test_capped_business_partition_and_cross_partition_duplicates_fail():
    web = AmazonWeb()
    web.jobs = [job(str(i)) for i in range(5)]
    with web.client() as client, pytest.raises(SourceError, match='result cap'):
        amazon.fetch_amazon_full_scan(client, BOARD)
    web.jobs = [job('same', 'alpha'), job('same', 'beta')]
    with web.client() as client, pytest.raises(SourceError, match='duplicate ID across'):
        amazon.fetch_amazon_full_scan(client, BOARD)


def test_country_metadata_must_match_the_independent_facet():
    web = AmazonWeb()
    original = web.handler
    def handler(request):
        response = original(request)
        if request.url.params.get('business_category[]'):
            data = response.json()
            data['jobs'][0]['country_code'] = 'CAN'
            return httpx.Response(200, json=data)
        return response
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(SourceError, match='independent counts'):
            amazon.fetch_amazon_full_scan(client, BOARD)


def test_four_workers_overlap_and_keep_out_of_order_pages_bounded():
    web = AmazonWeb()
    web.jobs = [job(str(i)) for i in range(8)]
    barrier, lock = Barrier(4, timeout=5), Lock()
    active = peak = 0
    original = web.handler
    def handler(request):
        nonlocal active, peak
        if request.url.params.get('business_category[]'):
            with lock:
                active += 1
                peak = max(peak, active)
            try:
                barrier.wait()
                return original(request)
            finally:
                with lock:
                    active -= 1
        return original(request)
    amazon.RESULT_CAP = 10  # restored by the autouse monkeypatch fixture
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert [p.job_id for p in amazon.fetch_amazon_full_scan(client, BOARD)] == list(map(str, range(8)))
    assert peak == 4


def test_failure_recovery_silent_baseline_and_simplify_alias_dedup():
    web = AmazonWeb()
    web.jobs = [job('123'), job('124')]
    web.failure = 'api_error'
    state, sent = State(), []
    config = Config('https://simplify.test/feed', frozenset({'amazon'}), (BOARD,))
    original = web.handler
    def handler(request):
        if request.url.host == 'simplify.test':
            data = [] if len(web.jobs) == 2 else [{
                'id': 'fallback', 'company_name': 'Amazon', 'title': 'Software Engineer Intern 125',
                'category': 'Software', 'active': True, 'is_visible': True,
                'locations': ['Austin, TX'], 'degrees': ["Bachelor's"],
                'url': 'https://amazon.jobs/en/jobs/125', 'date_posted': 1791158400}]
            return httpx.Response(200, json=data)
        return original(request)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        def poll():
            assert run(config, state, client, NOW,
                       {c: f'https://discord.test/{c}' for c in CHANNELS}, save=lambda: None,
                       post=lambda client, url, body: sent.append(body), unfiltered=True) == 0
        poll()
        assert not state.is_board_polled(BOARD.key)
        web.failure = None
        poll()
        assert state.is_board_polled(BOARD.key) and len(state.records) == 2 and not sent
        web.jobs.append(job('125'))
        poll()
        assert len(sent) == 1 and len(state.records) == 3
        poll()
        assert len(sent) == 1


class CandidateWeb:
    def __init__(self):
        self.rows = {
            'native': [job('1'), job('2'), job('3')],
            'intern': [job('1'), job('10517535')],
            'internship': [job('10517535'), job('4', title='Staff Engineer')],
            'co-op': [job('5', title='Software Engineer Co-op')],
            'coop': [],
        }
        self.calls = []
        self.fail = None

    def handler(self, request):
        if request.url.host == 'simplify.test':
            return httpx.Response(200, json=[])
        q = request.url.params
        label = 'native' if q.get('is_intern[]') == '1' else q['base_query']
        offset, limit = int(q['offset']), int(q['result_limit'])
        self.calls.append((label, offset))
        rows = self.rows[label]
        if self.fail == 'http' and label == 'coop':
            return httpx.Response(503)
        selected = deepcopy(rows[offset:offset + limit])
        if self.fail == 'short' and label == 'native' and offset:
            selected = []
        if self.fail == 'duplicate' and label == 'native' and offset:
            selected = [deepcopy(rows[0])]
        if self.fail == 'bad_candidate' and label == 'intern':
            selected[0]['basic_qualifications'] = None
        if self.fail == 'grad_conflict' and label == 'intern':
            selected[0]['title'] = 'Software Engineer Intern (PhD)'
        if self.fail == 'conflict' and label == 'intern':
            selected[0]['title'] = 'Other Software Engineer Intern'
        return httpx.Response(200, json={'hits': len(rows), 'jobs': selected, 'error': None})


@pytest.fixture
def candidate_web(monkeypatch):
    monkeypatch.setattr(amazon, 'RESULT_CAP', 100)
    return CandidateWeb()


def test_union_paginates_every_query_deduplicates_and_recovers_missing_native_asic(candidate_web):
    with httpx.Client(transport=httpx.MockTransport(candidate_web.handler)) as client:
        postings = amazon.fetch_amazon(client, BOARD)
    assert [p.job_id for p in postings] == ['1', '2', '3', '10517535', '5']
    assert ('native', 2) in candidate_web.calls
    assert {label for label, _ in candidate_web.calls} == {'native', 'intern', 'internship', 'co-op', 'coop'}


@pytest.mark.parametrize('failure', ['http', 'short', 'duplicate', 'bad_candidate', 'conflict', 'grad_conflict'])
def test_union_rejects_any_failed_query_or_inconsistent_candidate(candidate_web, failure):
    candidate_web.fail = failure
    with httpx.Client(transport=httpx.MockTransport(candidate_web.handler)) as client:
        with pytest.raises(SourceError):
            amazon.fetch_amazon(client, BOARD)


def test_union_count_churn_restarts_all_queries(candidate_web):
    original = candidate_web.handler
    calls = 0
    def handler(request):
        nonlocal calls
        if request.url.params.get('base_query') == 'intern':
            calls += 1
            if calls == 2:
                candidate_web.rows['intern'].append(job('6'))
        return original(request)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert '6' in {p.job_id for p in amazon.fetch_amazon(client, BOARD)}
    assert calls == 5  # Two initial/final pairs plus the new second page.


def test_union_continuous_churn_fails(candidate_web):
    original = candidate_web.handler
    def handler(request):
        if request.url.params.get('base_query') == 'intern':
            candidate_web.rows['intern'].append(job(str(1000 + len(candidate_web.rows['intern']))))
        return original(request)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(SourceError, match='three passes'):
            amazon.fetch_amazon(client, BOARD)


def test_union_cap_uses_complete_scan(candidate_web, monkeypatch):
    monkeypatch.setattr(amazon, 'RESULT_CAP', 3)
    marker = [amazon.parse_amazon(job('123'), BOARD)]
    called = []
    def full(client, board):
        called.append(board)
        return marker
    monkeypatch.setattr(amazon, 'fetch_amazon_full_scan', full)
    with httpx.Client(transport=httpx.MockTransport(candidate_web.handler)) as client:
        assert amazon.fetch_amazon(client, BOARD) == marker
    assert called == [BOARD]


def test_empty_union_requires_success_from_all_queries(candidate_web):
    candidate_web.rows = {k: [] for k in candidate_web.rows}
    with httpx.Client(transport=httpx.MockTransport(candidate_web.handler)) as client:
        assert amazon.fetch_amazon(client, BOARD) == []
    assert len(candidate_web.calls) == 10


def test_union_failure_then_silent_recovery_then_new_announcement(candidate_web):
    candidate_web.fail = 'http'
    config = Config('https://simplify.test/feed', frozenset(), (BOARD,))
    state, sent = State(), []
    with httpx.Client(transport=httpx.MockTransport(candidate_web.handler)) as client:
        def poll():
            assert run(config, state, client, NOW,
                       {c: f'https://discord.test/{c}' for c in CHANNELS}, save=lambda: None,
                       post=lambda client, url, body: sent.append(body)) == 0
        poll()
        assert not state.is_board_polled(BOARD.key)
        candidate_web.fail = None
        poll()
        assert state.is_board_polled(BOARD.key) and not sent
        candidate_web.rows['coop'].append(job('777'))
        poll()
        assert len(sent) == 1
        poll()
        assert len(sent) == 1
