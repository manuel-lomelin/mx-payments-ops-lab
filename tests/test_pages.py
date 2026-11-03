"""Smoke tests: every Streamlit page renders without raising."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parent.parent
PAGES = [ROOT / "Home.py", *sorted((ROOT / "pages").glob("*.py"))]


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.name)
def test_page_renders(page):
    at = AppTest.from_file(str(page), default_timeout=60).run()
    assert not at.exception, at.exception


def test_bulk_run_send_button():
    at = AppTest.from_file(str(ROOT / "pages" / "2_Bulk_Payment_Run.py"), default_timeout=60)
    at.run()
    at.button[0].click().run()
    assert not at.exception
    assert "billpay_run" in at.session_state


def test_workbench_blocks_a_threatening_edit():
    at = AppTest.from_file(str(ROOT / "pages" / "5_Collections_Workbench.py"), default_timeout=60)
    at.run()
    at.text_area[0].set_value(at.text_area[0].value + " Si no paga, irá a la cárcel.").run()
    at.button[0].click().run()
    assert not at.exception
    assert len(at.session_state["contact_log"].blocked) == 1
