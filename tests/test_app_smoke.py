from pathlib import Path

from streamlit.testing.v1 import AppTest


def test_demo_dashboard_renders_without_api_keys():
    app = AppTest.from_file(
        Path(__file__).parents[1] / "app.py", default_timeout=20
    ).run()
    assert not app.exception
    assert not app.error
    assert len(app.metric) >= 4
    assert len(app.tabs) == 5
