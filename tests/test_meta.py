"""Meta search completeness, structured fields, and pipeline recovery."""
import json
from datetime import UTC, datetime
from threading import Barrier, Lock
from urllib.parse import parse_qs

import httpx
import pytest

from intern_alerts.classify import classify, is_intern
from intern_alerts.config import Board, Config
from intern_alerts.main import run
from intern_alerts.models import CHANNELS
from intern_alerts.normalize import normalize_url
from intern_alerts.sources import SourceError
from intern_alerts.sources.meta import (
    SEARCH_URL, GRAPHQL_URL, SEARCH_QUERY, COUNT_QUERY, fetch_meta,
    parse_meta, parse_bootstrap, parse_query_ids, parse_search,
)
from intern_alerts.state import State

BOARD = Board('meta', 'meta', 'Meta')
URL = 'https://www.metacareers.com/profile/job_details/123/'
NOW = datetime(2026, 10, 5, tzinfo=UTC)


def job(**changes):
    return dict({'@type': 'JobPosting', 'title': 'Software Engineer Intern',
                 'description': 'Work on software', 'hiringOrganization': {'name': 'Meta'},
                 'identifier': {'value': 'different-structured-id'},
                 'datePosted': '2026-10-05T10:25:59-07:00', 'employmentType': 'INTERN',
                 'jobLocation': [{'name': 'Sunnyvale, CA', 'address': {'addressCountry': 'US'}},
                                 {'name': 'Toronto, ON', 'address': {'addressCountry': 'CA'}}]}, **changes)


def html(data=None):
    return '<script type="application/ld+json">' + json.dumps(job() if data is None else data) + '</script>'


def bootstrap():
    # Meta provides preloaded assets via HTML attributes and deferred assets in
    # Bootloader's JSON. A CSS resource belongs to the component but isn't JS.
    payload = {
        "rsrcMap": {"css": {"type": "css"}, "deferred": {
            "type": "js", "src": "https://static.xx.fbcdn.net/rsrc.php/deferred.js"}},
        "compMap": {"CPJobSearch.react": {"r": ["preloaded", "css", "deferred"]}},
    }
    box = {"define": [["LSD", [], {"token": "anonymous-test-token"}, 323]],
           "require": [["Bootloader", "handlePayload", None, [payload]]]}
    data = {"require": [["ScheduledServerJS", "handle", None, [{"__bbox": box}]]]}
    return ('<script src="https://static.xx.fbcdn.net/rsrc.php/preloaded.js" '
            'data-bootloader-hash="preloaded"></script>'
            '<script type="application/json" data-sjs>' + json.dumps(data) + '</script>')


def query_script(search_id="111", count_id="222"):
    # Reduced from Meta's actual anonymous search assets: the .graphql module
    # imports an operation module whose export supplies the current numeric ID.
    return ''.join(
        f'__d("{name}_candidate_portalRelayOperation",[],(function(t,n,r,o,a,i){{'
        f'a.exports="{doc_id}"}}),null);'
        f'__d("{name}.graphql",["{name}_candidate_portalRelayOperation"],'
        f'(function(t,n,r,o,a,i){{var e={{params:{{id:n("{name}_candidate_portalRelayOperation")}}}};'
        'a.exports=e}),null);'
        for name, doc_id in [(SEARCH_QUERY, search_id), (COUNT_QUERY, count_id)])


def summary(job_id, **changes):
    return {"id": str(job_id), "title": "Software Engineer Intern",
            "locations": ["Sunnyvale, CA"], "teams": ["Internship - Engineering, Tech & Design"],
            "sub_teams": ["Engineering"], **changes}


def search_route(request, ids):
    if str(request.url) == SEARCH_URL:
        return httpx.Response(200, text=bootstrap())
    if request.url.host == "static.xx.fbcdn.net":
        return httpx.Response(200, text=query_script() if "deferred" in request.url.path else "// common")
    if str(request.url) == GRAPHQL_URL:
        form = parse_qs(request.content.decode())
        name = form["fb_api_req_friendly_name"][0]
        assert form["doc_id"] == ["111" if name == SEARCH_QUERY else "222"]
        variables = json.loads(form["variables"][0])
        assert variables["search_input"]["roles"] == []
        assert variables["search_input"]["q"] is None
        data = {"all_jobs": [summary(i) for i in ids]} if name == SEARCH_QUERY else {"job_count": len(ids)}
        return httpx.Response(200, json={"data": {"job_search_with_featured_jobs_v2": data},
                                       "extensions": {"is_final": True}})
    return None


def test_fields_use_url_identity_and_real_posting_date():
    p = parse_meta(html(), URL, BOARD)
    assert p.job_id == '123'
    assert p.board_key == 'meta:meta'
    assert p.locations == ('Sunnyvale, CA, United States', 'Toronto, ON, Canada')
    assert p.posted_at == datetime(2026, 10, 5, 17, 25, 59, tzinfo=UTC)
    assert p.degrees == ()
    assert classify(p).announce


def test_graph_and_label_without_title_signal():
    p = parse_meta(html({'@graph': [job(title='Software Engineer', employmentType=['INTERN'])]}), URL, BOARD)
    assert is_intern(p)
    assert classify(p).announce


@pytest.mark.parametrize('title', ['Software Engineer Intern, PhD', 'High School Software Intern'])
def test_degree_and_high_school_policy(title):
    assert not classify(parse_meta(html(job(title=title)), URL, BOARD)).announce


def test_title_signal_with_full_time_label():
    assert is_intern(parse_meta(html(job(employmentType='FULL_TIME')), URL, BOARD))


def test_remote_country_restriction_and_unknown_country():
    p = parse_meta(html(job(jobLocation=[], jobLocationType='TELECOMMUTE',
                           applicantLocationRequirements={'name': 'India'})), URL, BOARD)
    assert not classify(p).announce
    p = parse_meta(html(job(jobLocation={'name': 'City', 'address': {'addressCountry': 'ZZ'}})), URL, BOARD)
    assert p.locations == ('City, Country ZZ',)
    assert not classify(p).announce


@pytest.mark.parametrize('data', [[], [job(), job()], job(description=''), job(datePosted='2026-10-05'),
                                 job(hiringOrganization={'name': 'Other'}), job(jobLocation='bad')])
def test_untrusted_details_fail(data):
    with pytest.raises((ValueError, KeyError, TypeError)):
        parse_meta(html(data), URL, BOARD)


def test_details_overlap_with_four_workers_and_keep_search_order():
    barrier = Barrier(4, timeout=5)
    lock = Lock()
    active = peak = 0

    def handler(request):
        nonlocal active, peak
        response = search_route(request, range(8))
        if response is not None:
            return response
        with lock:
            active += 1
            peak = max(peak, active)
            assert active <= 4
        try:
            barrier.wait()
            barrier.wait()
            return httpx.Response(200, text=html())
        finally:
            with lock:
                active -= 1

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        postings = fetch_meta(client, BOARD)
    assert peak == 4
    assert [p.job_id for p in postings] == list(map(str, range(8)))


@pytest.mark.parametrize('status,body', [(503, 'down'), (200, '<html>Login</html>'),
                                       (200, '<script type="application/ld+json">{bad}</script>')])
def test_any_failed_detail_discards_entire_board(status, body):
    def handler(request):
        response = search_route(request, [123, 456])
        if response is not None:
            return response
        return httpx.Response(status if '456' in str(request.url) else 200,
                              text=body if '456' in str(request.url) else html())
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(SourceError, match='meta:meta'):
            fetch_meta(client, BOARD)


def test_redirect_to_other_job_is_rejected():
    def handler(request):
        response = search_route(request, [123])
        if response is not None:
            return response
        if '123' in str(request.url):
            return httpx.Response(302, headers={'Location': URL.replace('123', '456')})
        return httpx.Response(200, text=html())
    with httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True) as client:
        with pytest.raises(SourceError, match='redirected'):
            fetch_meta(client, BOARD)


def test_aliases_deduplicate_and_other_hosts_are_untouched():
    assert normalize_url('https://www.metacareers.com/jobs/123/?utm_source=Simplify') == normalize_url(URL)
    assert normalize_url('https://other.test/jobs/123') != normalize_url(URL)


@pytest.mark.parametrize("failure_kind", ["detail", "search"])
def test_failure_recovery_silent_baseline_then_new_posting_and_fallback_duplicate(failure_kind):
    ids = [123]
    failed = True
    sent = []
    config = Config('https://simplify.test/feed', frozenset({'meta'}), (BOARD,))
    webhooks = {channel: f'https://discord.test/{channel}' for channel in CHANNELS}

    def handler(request):
        if request.url.host == 'discord.test':
            sent.append(json.loads(request.content)['content'])
            return httpx.Response(200, json={'id': '1'})
        if request.url.host == 'simplify.test':
            return httpx.Response(200, json=[] if 456 not in ids else [{
                'id': 'fallback', 'company_name': 'Meta', 'title': 'Software Engineer Intern',
                'category': 'Software', 'active': True, 'is_visible': True,
                'locations': ['Sunnyvale, CA'], 'degrees': ["Bachelor's"],
                'url': 'https://www.metacareers.com/jobs/456/', 'date_posted': 1791221159}])
        response = search_route(request, ids)
        if (failed and failure_kind == "search" and request.method == 'POST'
                and parse_qs(request.content.decode())['doc_id'] == ['111']):
            return httpx.Response(200, json={
                'data': {'job_search_with_featured_jobs_v2': {'all_jobs': []}},
                'extensions': {'is_final': True}})
        if response is not None:
            return response
        return httpx.Response(200, text='<html>Login</html>' if failed and failure_kind == 'detail' else html())

    state = State()
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        def poll():
            assert run(config, state, client, NOW, webhooks, save=lambda: None) == 0
        poll()
        assert not state.is_board_polled(BOARD.key)
        failed = False
        poll()
        assert state.is_board_polled(BOARD.key)
        assert not sent
        ids.append(456)
        poll()
        assert len(sent) == 1
        assert len(state.records) == 2
        poll()
        assert len(sent) == 1


def test_live_fixture_shape():
    from pathlib import Path
    data = json.loads((Path(__file__).parent / 'fixtures/meta.json').read_text())
    p = parse_meta(html(data), URL, BOARD)
    assert p.title == 'Electrical Engineering Intern'
    assert p.locations == ('Sunnyvale, CA, United States', 'New York, NY, United States')
    assert p.employment_type == 'INTERN'
    assert p.degrees == ()  # merged qualifications are not required-degree evidence
    assert classify(p).announce


def test_transient_server_rendering_failure_is_retried():
    attempts = 0
    def handler(request):
        nonlocal attempts
        response = search_route(request, [123])
        if response is not None:
            return response
        attempts += 1
        return httpx.Response(200, text='<html>SSR failed</html>' if attempts == 1 else html())
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert len(fetch_meta(client, BOARD)) == 1
    assert attempts == 2


def test_bootstrap_maps_preloaded_deferred_and_css_resources():
    token, urls = parse_bootstrap(bootstrap())
    assert token == 'anonymous-test-token'
    assert urls == ['https://static.xx.fbcdn.net/rsrc.php/preloaded.js',
                    'https://static.xx.fbcdn.net/rsrc.php/deferred.js']
    with pytest.raises(ValueError, match='asset URL'):
        parse_bootstrap(bootstrap().replace('static.xx.fbcdn.net', 'other.test'))


def test_query_ids_are_discovered_again_after_a_site_release():
    assert parse_query_ids([query_script('87654321', '12345678')]) == {
        SEARCH_QUERY: '87654321', COUNT_QUERY: '12345678'}
    with pytest.raises(ValueError, match='query IDs'):
        parse_query_ids([query_script(), query_script('333', '444')])
    with pytest.raises(ValueError, match='query IDs'):
        parse_query_ids(['// search modules no longer available'])


@pytest.mark.parametrize('jobs,expected', [
    ([summary(1)], 2), ([summary(1), summary(1)], 2),
    ([summary('not-an-id')], 1), ([summary(1, locations='US')], 1),
    ([summary(1, title='')], 1),
])
def test_truncated_or_malformed_search_fails_board(jobs, expected):
    def handler(request):
        response = search_route(request, range(expected))
        if request.method == 'POST' and parse_qs(request.content.decode())['doc_id'] == ['111']:
            return httpx.Response(200, json={
                'data': {'job_search_with_featured_jobs_v2': {'all_jobs': jobs}},
                'extensions': {'is_final': True}})
        assert response is not None  # no details should be attempted
        return response
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(SourceError):
            fetch_meta(client, BOARD)


@pytest.mark.parametrize('payload', [
    {'data': {}, 'errors': [{'message': 'invalid query'}], 'extensions': {'is_final': True}},
    {'data': {'job_search_with_featured_jobs_v2': {'job_count': 1}}},
    {'data': {'job_search_with_featured_jobs_v2': {'job_count': True}},
     'extensions': {'is_final': True}},
])
def test_http_200_graphql_failure_is_not_an_empty_success(payload):
    def handler(request):
        if request.method == 'POST':
            return httpx.Response(200, json=payload)
        return search_route(request, [123])
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(SourceError):
            fetch_meta(client, BOARD)


def test_count_change_after_details_rejects_board():
    counts = 0
    def handler(request):
        nonlocal counts
        response = search_route(request, [123])
        if request.method == 'POST' and parse_qs(request.content.decode())['doc_id'] == ['222']:
            counts += 1
            if counts == 2:
                return httpx.Response(200, json={
                    'data': {'job_search_with_featured_jobs_v2': {'job_count': 2}},
                    'extensions': {'is_final': True}})
        return response if response is not None else httpx.Response(200, text=html())
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(SourceError, match='count changed'):
            fetch_meta(client, BOARD)


def test_empty_search_with_two_verified_zero_counts_succeeds():
    with httpx.Client(transport=httpx.MockTransport(lambda r: search_route(r, []))) as client:
        assert fetch_meta(client, BOARD) == []


def test_only_undergrad_title_or_team_candidates_require_details():
    jobs = [summary(1, title='Software Engineer', teams=[]),
            summary(2, title='Research Scientist Intern, PhD'),
            summary(3, title='Software Engineer', teams=['Internship - Engineering, Tech & Design'])]
    details = []
    def handler(request):
        response = search_route(request, [1, 2, 3])
        if request.method == 'POST' and parse_qs(request.content.decode())['doc_id'] == ['111']:
            return httpx.Response(200, json={
                'data': {'job_search_with_featured_jobs_v2': {'all_jobs': jobs}},
                'extensions': {'is_final': True}})
        if response is not None:
            return response
        details.append(str(request.url))
        return httpx.Response(200, text=html(job(title='Software Engineer', employmentType='FULL_TIME')))
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        postings = fetch_meta(client, BOARD)
    assert details == ['https://www.metacareers.com/profile/job_details/3/']
    assert classify(postings[0]).announce


def test_live_search_fixture_covers_undergrad_grad_and_full_time_signals():
    from pathlib import Path
    jobs = json.loads((Path(__file__).parent / 'fixtures/meta-search.json').read_text())
    assert len(parse_search({'all_jobs': jobs}, 3)) == 3
    assert jobs[0]['title'] == 'Electrical Engineering Intern'
    assert jobs[1]['title'].endswith('(PhD)')
    assert not is_intern(parse_meta(html(job(title=jobs[2]['title'], employmentType='FULL_TIME')),
                                   URL, BOARD))
