from datetime import UTC, datetime

import pytest

from intern_alerts.classify import (
    classify,
    is_intern,
    is_undergrad,
    job_channels,
    location_regions,
)
from intern_alerts.models import Posting


def posting(source="greenhouse", title="Software Engineer Intern", locations=("Seattle, WA",), **kw):
    return Posting(
        source=source,
        board_key=f"{source}:test",
        job_id="1",
        company="Test",
        title=title,
        locations=tuple(locations),
        url="https://example.com/1",
        posted_at=datetime(2026, 10, 1, tzinfo=UTC),
        **kw,
    )


# Internship detection


@pytest.mark.parametrize(
    "title, expected",
    [
        ("Software Engineer, Intern (Summer or Winter)", True),
        ("Data Analyst, Intern", True),
        ("Summer Internship - Firmware", True),
        ("Hardware Co-op", True),
        ("Interns: Quant Research", True),
        ("Internal Audit Data Analytics Lead", False),
        ("International Tax Manager", False),
        ("Software Engineer", False),
    ],
)
def test_greenhouse_intern_title(title, expected):
    assert is_intern(posting(title=title)) is expected


def test_ashby_uses_employment_type_not_title():
    assert is_intern(posting(source="ashby", title="Applied Scientist", employment_type="Intern"))
    assert not is_intern(
        posting(source="ashby", title="Software Engineer Intern", employment_type="FullTime")
    )


def test_high_school_programs_excluded_from_every_source():
    title = "High School Internship, Software Engineering (Summer 2027)"
    assert not is_intern(posting(title=title))
    assert not is_intern(posting(source="ashby", title=title, employment_type="Intern"))
    assert not is_intern(posting(source="simplify", title="High-School Intern", category="Software"))


def test_simplify_always_intern():
    assert is_intern(posting(source="simplify", title="Anything", category="Software"))


# Degree level


@pytest.mark.parametrize(
    "degrees, expected",
    [
        ((), True),  # not stated
        (("Bachelor's",), True),
        (("Bachelor's", "Master's"), True),
        (("Associate's",), True),
        (("Master's", "PhD"), False),
        (("PhD",), False),
        (("MBA",), False),
    ],
)
def test_simplify_degrees(degrees, expected):
    p = posting(source="simplify", title="Software Engineer Intern", category="Software",
                degrees=degrees)
    assert is_undergrad(p) is expected


@pytest.mark.parametrize(
    "title, expected",
    [
        ("Software Engineer Intern", True),
        ("PhD Data Scientist, Intern", False),
        ("Software Engineer Intern - MS", False),
        ("Master's Research Intern", False),
        ("MBA Product Intern", False),
        ("Software Engineer Intern (BS/MS)", True),
        ("Undergraduate or PhD Research Intern", True),
        ("Systems Intern", True),  # "ms" only as a whole word
    ],
)
def test_degree_in_title(title, expected):
    assert is_undergrad(posting(title=title)) is expected


def test_phd_posting_not_announced():
    assert not classify(posting(title="PhD Data Scientist, Intern")).announce


# Job type


@pytest.mark.parametrize(
    "title, expected",
    [
        ("Software Engineer Intern", {"swe"}),
        ("Full-Stack Developer Intern", {"swe"}),
        ("iOS Engineering Intern", {"swe"}),
        ("Machine Learning Intern", {"data_ml"}),
        ("AI Research Intern", {"data_ml"}),
        ("Data Analyst, Intern", {"data_ml"}),
        ("ML Firmware Intern", {"data_ml", "hardware"}),
        ("FPGA Design Intern", {"hardware"}),
        ("Quantitative Trading Intern", {"quant"}),
        ("Mechanical Engineering Intern", {"other_eng"}),
        ("Associate Product Manager Intern", {"product"}),
        ("Marketing Intern", set()),
        ("Maintenance Technician Intern", set()),  # "ai" must not match inside words
        ("HTML Email Intern", set()),  # "ml" must not match inside words
        ("Biostudios Intern", set()),  # "ios" must not match inside words
    ],
)
def test_title_keywords(title, expected):
    assert job_channels(posting(title=title)) == expected


@pytest.mark.parametrize(
    "category, expected",
    [
        ("Software", {"swe"}),
        ("AI/ML/Data", {"data_ml"}),
        ("Hardware", {"hardware"}),
        ("Quant", {"quant"}),
        ("Product", {"product"}),
        ("Quantitative Finance", {"quant"}),
        ("Something New", set()),
    ],
)
def test_simplify_category(category, expected):
    assert job_channels(posting(source="simplify", title="x", category=category)) == expected


# Regions


@pytest.mark.parametrize(
    "location, expected",
    [
        ("Seattle, WA", {"US"}),
        ("NYC", {"US"}),
        ("SF", {"US"}),
        ("South SF", {"US"}),
        ("New York, NY (HQ)", {"US"}),
        ("Austin, TX", {"US"}),
        ("Cambridge, MA", {"US"}),
        ("New York, Seattle, South San Francisco HQ", {"US"}),
        ("Toronto, ON, Canada", {"Canada"}),
        ("Montréal, QC", {"Canada"}),
        ("London, UK", {"UK"}),
        ("Cambridge, England", {"UK"}),
        ("Dublin", {"Europe"}),
        ("Berlin, Germany", {"Europe"}),
        ("Seattle or London", {"US", "UK"}),
        ("Remote", {"Remote"}),
        ("Remote (US)", {"Remote"}),
        ("Remote (Canada)", {"Remote"}),
        ("Remote - United States", {"Remote"}),
        ("Remote (India)", set()),
        ("Singapore", set()),
        ("Bangalore, India", set()),
        ("Cambridge", set()),  # ambiguous on its own
    ],
)
def test_location_regions(location, expected):
    assert location_regions(location) == expected


# Whole classification


def test_multi_region_posting():
    result = classify(
        posting(source="ashby", employment_type="Intern",
                locations=("New York, NY (HQ)", "Remote (Canada)", "Miami, FL", "Singapore"))
    )
    assert result.announce
    assert result.regions == {"US", "Remote"}
    assert result.unrecognized == ("Singapore",)


@pytest.mark.parametrize(
    "location",
    ["Flexible - Any SpaceX Site", "BLANK,BLANK,Multiple Locations", "In-Office", "Various Locations", ""],
)
def test_vague_location_goes_under_unspecified(location):
    result = classify(posting(title="Software Engineering Internship", locations=(location,)))
    assert result.announce
    assert result.regions == {"Unspecified"}
    assert result.unrecognized == ()


def test_vague_location_uses_place_in_title():
    result = classify(
        posting(title="Software Engineer Intern (2027) - Austin, TX", locations=("In-Office",))
    )
    assert result.regions == {"US"}


def test_vague_location_ignored_when_another_location_is_known():
    result = classify(posting(locations=("Multiple Locations", "Toronto, ON")))
    assert result.regions == {"Canada"}


def test_no_region_is_not_announced():
    result = classify(posting(locations=("Singapore",)))
    assert not result.announce
    assert result.unrecognized == ("Singapore",)


def test_non_intern_ignored_without_logging_locations():
    result = classify(posting(title="Staff Software Engineer", locations=("Mars Base",)))
    assert not result.announce
    assert result.unrecognized == ()


def test_no_channel_ignored():
    assert not classify(posting(title="Marketing Intern")).announce
