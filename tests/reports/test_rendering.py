import pytest

from reports.rendering import process_html

from .utils import assert_html_equal


@pytest.mark.django_db
@pytest.mark.parametrize(
    "html",
    [
        """
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
        """
            <html>
                <body>
                    <p>foo</p>
                    <div>Stuff</div>
                </body>
            </html>
        """,
        """
            <p>foo</p>
            <div>Stuff</div>
        """,
        """
            <script>Some Javascript nonsense</script>
            <p>foo</p>
            <div>
                Stuff
                <script>Some more Javascript nonsense</script>
            </div>
        """,
        """
            <p onclick="alert('BOOM!')">foo</p>
            <div>
                Stuff
            </div>
        """,
        """
            <style>Mmmm, lovely styles...</style>
            <p>foo</p>
            <div>
                Stuff
                <style>MOAR STYLZ</style>
            </div>
        """,
        """
            <p style="color: red;">foo</p>
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
        "Strips out inline handlers",
        "Strips out all style tags",
        "Strips out inline styles",
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


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("input_html", "expected"),
    [
        (
            """
                <table>
                    <tr><td>something</td></tr>
                </table>
            """,
            """
                <div class="overflow-wrapper">
                    <table>
                        <tr><td>something</td></tr>
                    </table>
                </div>
            """,
        ),
        (
            """
                <html>
                    <body>
                        <table>
                            <tr><td>something</td></tr>
                        </table>
                    </body>
                </html>
            """,
            """
                <div class="overflow-wrapper">
                    <table>
                        <tr><td>something</td></tr>
                    </table>
                </div>
            """,
        ),
        (
            """
                <table>
                    <tr><td>something</td></tr>
                </table>
                <table>
                    <tr><td>something else</td></tr>
                </table>
            """,
            """
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
            """
                <pre>Some code or something here</pre>
            """,
            """
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
def test_html_processing_wraps_scrollables(input_html, expected):
    html = process_html(input_html)
    assert_html_equal(html, expected)
