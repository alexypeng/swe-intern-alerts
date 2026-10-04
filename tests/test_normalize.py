from intern_alerts.normalize import normalize_locations, normalize_text, normalize_url


def test_url_keeps_job_id_query_param():
    # Stripe's Greenhouse jobs live on stripe.com with the job ID in the query string.
    assert (
        normalize_url("https://stripe.com/jobs/search?gh_jid=8128745")
        == "https://stripe.com/jobs/search?gh_jid=8128745"
    )


def test_url_drops_tracking_params():
    assert (
        normalize_url("https://stripe.com/jobs/search?utm_source=Simplify&gh_jid=1&ref=Simplify")
        == "https://stripe.com/jobs/search?gh_jid=1"
    )


def test_url_ignores_case_www_scheme_fragment_and_trailing_slash():
    assert (
        normalize_url("http://WWW.Example.com/jobs/1/#apply")
        == normalize_url("https://example.com/jobs/1")
    )


def test_url_sorts_params():
    assert normalize_url("https://a.com/j?b=2&a=1") == normalize_url("https://a.com/j?a=1&b=2")


def test_url_greenhouse_host_alias():
    assert normalize_url("https://boards.greenhouse.io/acme/jobs/123") == normalize_url(
        "https://job-boards.greenhouse.io/acme/jobs/123"
    )


def test_url_different_jobs_stay_different():
    assert normalize_url("https://stripe.com/jobs/search?gh_jid=1") != normalize_url(
        "https://stripe.com/jobs/search?gh_jid=2"
    )


def test_text():
    assert normalize_text("  Software Engineer Intern - Summer  2027! ") == (
        "software engineer intern summer 2027"
    )
    assert normalize_text("Montréal, QC") == "montreal qc"
    assert normalize_text("Data_Science/ML") == "data science ml"


def test_locations_order_independent():
    assert normalize_locations(["NYC", "Seattle, WA"]) == normalize_locations(["seattle wa", "nyc"])
