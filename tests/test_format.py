from datetime import UTC, datetime

from intern_alerts.format import MAX_LENGTH, build_messages, escape, posting_block
from intern_alerts.models import Posting


def posting(n=1, title="Software Engineer Intern", locations=("Seattle, WA",), day=4, company="Stripe"):
    return Posting(
        source="greenhouse",
        board_key="greenhouse:stripe",
        job_id=str(n),
        company=company,
        title=title,
        locations=tuple(locations),
        url=f"https://stripe.com/jobs/search?gh_jid={n}",
        posted_at=datetime(2026, 10, day, tzinfo=UTC),
    )


def test_posting_block():
    assert posting_block(posting(locations=("Seattle, WA", "NYC"))) == (
        "**Stripe** — [Software Engineer Intern](<https://stripe.com/jobs/search?gh_jid=1>)\n"
        "Seattle, WA · NYC · Oct 4"
    )


def test_long_location_list_is_shortened():
    block = posting_block(posting(locations=[f"City {i}" for i in range(29)]))
    assert block.endswith("City 0 · City 1 · City 2 · +26 more · Oct 4")


def test_escape_markdown():
    assert escape("C++ *Systems* [Intern]_x") == r"C++ \*Systems\* \[Intern\]\_x"


def test_regions_in_order_with_headers_and_newest_first():
    old = posting(1, title="Old", day=1)
    new = posting(2, title="New", day=3)
    canada = posting(3, title="Toronto Role")
    [message] = build_messages([
        (old, frozenset({"US"})),
        (canada, frozenset({"Canada"})),
        (new, frozenset({"US"})),
    ])
    content = message.content
    assert content.startswith("## 🇺🇸 US\n**Stripe** — [New]")
    assert content.index("[New]") < content.index("[Old]") < content.index("## 🇨🇦 Canada")
    assert "## 🇪🇺 Europe" not in content  # empty regions skipped
    assert message.postings == [new, old, canada]


def test_multi_region_posting_appears_under_each_but_recorded_once():
    p = posting(locations=("Seattle, WA", "London, UK"))
    [message] = build_messages([(p, frozenset({"US", "UK"}))])
    assert message.content.count("[Software Engineer Intern]") == 2
    assert message.postings == [p]


def test_split_at_limit_after_last_posting_that_fits():
    postings = [posting(i, title=f"Role {i:03d} " + "x" * 80) for i in range(60)]
    messages = build_messages((p, frozenset({"US"})) for p in postings)
    assert len(messages) > 1
    assert all(len(m.content) <= MAX_LENGTH for m in messages)
    assert messages[0].content.startswith("## 🇺🇸 US")
    assert not messages[1].content.startswith("##")  # headers are not repeated
    assert sum(len(m.postings) for m in messages) == 60
    for m in messages:  # no posting is cut in half
        assert m.content.count("**Stripe**") == len(m.postings)


def test_header_never_left_alone_at_end_of_message():
    filler = [posting(i, title="y" * 280) for i in range(6)]
    canada = posting(99, title="Canada Role")
    messages = build_messages(
        [(p, frozenset({"US"})) for p in filler] + [(canada, frozenset({"Canada"}))]
    )
    for m in messages:
        assert not m.content.rstrip().endswith("Canada")
    canada_message = next(m for m in messages if "## 🇨🇦 Canada" in m.content)
    assert "[Canada Role]" in canada_message.content


def test_no_postings_no_messages():
    assert build_messages([]) == []
