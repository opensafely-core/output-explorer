from datetime import date, timedelta
from uuid import uuid4

import pytest
from bs4 import BeautifulSoup
from django.urls import reverse
from model_bakery import baker

from reports.models import Category, Report
from reports.views import process_html


@pytest.mark.django_db
def test_landing_view(client):
    """Test landing view context"""
    assert Report.objects.exists() is False
    # By default we have one Category, set up in the migration
    assert Category.objects.count() == 1
    response = client.get(reverse("gateway:landing"))

    # There is a category, but it isn't included in the context because it has no associated Reports
    assert list(response.context["categories"]) == []

    # when Reports exist, their categories are included in the context
    baker.make_recipe("reports.dummy_report")
    baker.make_recipe("reports.dummy_report", menu_name="test1")
    response = client.get(reverse("gateway:landing"))
    assert list(response.context["categories"]) == list(Category.objects.all())


@pytest.mark.django_db
@pytest.mark.parametrize(
    "reports,expected",
    [
        (
            {
                "test1": {"publication_date": date(2021, 2, 1)},
                "test2": {
                    "publication_date": date(2021, 1, 1),
                    "last_updated": date(2021, 3, 1),
                },
            },
            [
                ("test2", "updated", date(2021, 3, 1)),
                ("test1", "published", date(2021, 2, 1)),
                ("test2", "published", date(2021, 1, 1)),
            ],
        ),
        (
            {
                "test1": {"publication_date": date(2021, 2, 1)},
                "test2": {
                    "publication_date": date(2021, 1, 1),
                    "last_updated": date(2021, 1, 1),
                },
            },
            [
                ("test1", "published", date(2021, 2, 1)),
                ("test2", "published", date(2021, 1, 1)),
            ],
        ),
        (
            # setup 12 reports published on 1st, 2nd, ...12th
            {
                f"test{i}": {"publication_date": date(2021, 1, 1) + timedelta(days=i)}
                for i in range(12)
            },
            # expect 11 reports published on 10th, 9th, ...1st
            [
                (
                    f"test{11 - i}",
                    "published",
                    date(2021, 1, 1) + timedelta(days=(11 - i)),
                )
                for i in range(10)
            ],
        ),
    ],
    ids=[
        "Test reports with both publication and last updated are included, in reverse order",
        "Test reports with identical publication and updated dates only show publication",
        "Test only 10 most recent events are shown",
    ],
)
def test_landing_view_recent_activity(client, reports, expected):
    for menu_name, report_fields in reports.items():
        baker.make_recipe("reports.dummy_report", menu_name=menu_name, **report_fields)

    response = client.get(reverse("gateway:landing"))
    # only reports with dates are shown in recent_activity
    # report activity is returned in reverse date order
    # reports have additional annotation fields "activity" and "activity_date"
    context_report = [
        (report.menu_name, report.activity, report.activity_date)
        for report in response.context["recent_activity"]
    ]
    assert context_report == expected


@pytest.mark.django_db
def test_report_view(client):
    """Test a single report page"""
    # report for a real file
    report = baker.make_recipe("reports.real_report")
    response = client.get(report.get_absolute_url())
    assert_html_equal(
        response.context["notebook_contents"],
        """
            <h1>A Test Output HTML file</h1>
            <p>The test content</p>
        """,
    )


@pytest.mark.django_db
def test_report_view_with_invalid_token(client):
    """Test a single report page"""
    # report for a real file
    report = baker.make_recipe("reports.real_report")
    invalid_uuid = uuid4()
    response = client.get(
        reverse("reports:report_view", args=(report.slug, invalid_uuid))
    )
    assert response.status_code == 302
    assert response.url == report.get_absolute_url()


def assert_last_cache_log(log_entries, expected_log_items):
    last_cache_log = next(
        (
            log
            for log in reversed(log_entries.entries)
            if "cache" in log["event"].lower()
        ),
        None,
    )
    if expected_log_items is None:
        assert last_cache_log is None
    else:
        for key, value in expected_log_items.items():
            assert last_cache_log[key] == value
    log_entries.entries.clear()


@pytest.mark.django_db
def test_report_view_cache(client, log_output):
    """
    Test caching a single report page.
    """
    report = baker.make_recipe("reports.real_report")

    # nothing cached yet
    response = client.get(report.get_absolute_url())
    assert_last_cache_log(
        log_output, {"report_id": report.id, "slug": "test", "event": "Cache missed"}
    )
    assert response.status_code == 200

    # fetch it again
    client.get(report.get_absolute_url())
    assert_last_cache_log(log_output, None)
    assert response.status_code == 200

    # force update
    response = client.get(report.get_absolute_url() + "?force-update=")
    old_token = report.cache_token
    report.refresh_from_db()
    assert old_token != report.cache_token
    assert_last_cache_log(
        log_output,
        {
            "report_id": report.id,
            "slug": "test",
            "event": "Cache token refreshed, redirecting...",
        },
    )
    assert response.status_code == 302
    assert response.url == report.get_absolute_url()


@pytest.mark.parametrize(
    "html",
    [
        b"""
            <!DOCTYPE html>
            <html>
                <head>
                    <style type="text/css">body {margin: 0;}</style>
                    <style type="text/css">a {background-color: red;}</style>
                    <script src="https://a-js-package.js"></script>
                </head>
                <body>
                    <p>foo</p>
                    <div>Stuff</div>
                </body>
            </html>
        """,
        b"""
            <html>
                <body>
                    <p>foo</p>
                    <div>Stuff</div>
                </body>
            </html>
        """,
        b"""
            <p>foo</p>
            <div>Stuff</div>
        """,
        b"""
            <script>Some Javascript nonsense</script>
            <p>foo</p>
            <div>
                Stuff
                <script>Some more Javascript nonsense</script>
            </div>
        """,
        b"""
            <style>Mmmm, lovely styles...</style>
            <p>foo</p>
            <div>
                Stuff
                <style>MOAR STYLZ</style>
            </div>
        """,
    ],
    ids=[
        "Extracts body from HTML full document",
        "Extracts body from HTML document without head",
        "Returns HTML without body tags unchanged",
        "Strips out all script tags",
        "Strips out all style tags",
    ],
)
def test_html_processing_extracts_body(html):
    assert_html_equal(
        process_html(html),
        """
            <p>foo</p>
            <div>Stuff</div>
        """,
    )


@pytest.mark.parametrize(
    ("input", "report"),
    [
        (
            b"""
                <table>
                    <tr><td>something</td></tr>
                </table>
            """,
            b"""
                <div class="overflow-wrapper">
                    <table>
                        <tr><td>something</td></tr>
                    </table>
                </div>
            """,
        ),
        (
            b"""
                <html>
                    <body>
                        <table>
                            <tr><td>something</td></tr>
                        </table>
                    </body>
                </html>
            """,
            b"""
                <div class="overflow-wrapper">
                    <table>
                        <tr><td>something</td></tr>
                    </table>
                </div>
            """,
        ),
        (
            b"""
                <table>
                    <tr><td>something</td></tr>
                </table>
                <table>
                    <tr><td>something else</td></tr>
                </table>
            """,
            b"""
                <div class="overflow-wrapper">
                    <table>
                        <tr><td>something</td></tr>
                    </table>
                </div>
                <div class="overflow-wrapper">
                    <table>
                        <tr><td>something else</td></tr>
                    </table>
                </div>
            """,
        ),
        (
            b"""
                <pre>Some code or something here</pre>
            """,
            b"""
                <div class="overflow-wrapper">
                    <pre>Some code or something here</pre>
                </div>
            """,
        ),
    ],
    ids=[
        "Wraps single table in overflow wrappers",
        "Wraps table in full document in overflow wrappers",
        "Wraps multiple tables in overflow wrappers",
        "Wraps <pre> elements in overflow wrappers",
    ],
)
def test_html_processing_wraps_scrollables(input, report):
    assert_html_equal(process_html(input), report)


def assert_html_equal(actual, expected):
    assert normalize(actual) == normalize(expected)


def normalize(html):
    return BeautifulSoup(html.strip(), "html.parser").prettify()