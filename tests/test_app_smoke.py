"""End-to-end smoke test for the Portfolio tab using Streamlit's AppTest
harness — runs app.py for real (no uploader interaction needed; we seed
session_state directly) and asserts it renders without raising, covering
the actual Streamlit rendering code that unit tests in test_reconciliation
/ test_adapters can't reach."""
from datetime import date

from streamlit.testing.v1 import AppTest

from src.core.unified import AssetClass, SourceSystem, UnifiedRecord, make_record_id
from src.reconciliation.delta import CHANGED, NEW, Delta
from src.sources.personal_sheet import InvestmentItem, PersonalFinanceData


def _canonical_record():
    return UnifiedRecord(
        record_id=make_record_id(SourceSystem.PERSONAL_SHEET, "Personal Sheet", "Fund A", AssetClass.MUTUAL_FUND),
        asset_class=AssetClass.MUTUAL_FUND,
        source_system=SourceSystem.PERSONAL_SHEET,
        identifier="Fund A",
        identifier_type="name",
        name="Fund A",
        current_value=1000.0,
        account_name="Personal Sheet",
    )


def test_portfolio_tab_renders_with_no_data():
    at = AppTest.from_file("app.py", default_timeout=30)
    # No sources loaded at all -> the existing st.stop() gate should fire,
    # same as before this change; just confirm nothing raises getting there.
    at.run()
    assert not at.exception


def test_portfolio_tab_renders_with_canonical_records_and_no_pending_review():
    at = AppTest.from_file("app.py", default_timeout=30)
    at.session_state["sheet_data"] = PersonalFinanceData(
        investments=[InvestmentItem(section="Mutual Funds", subsection=None, name="Fund A", amount=1000.0, current_value=1000.0, monthly_value=None, details=None)],
        sheets_found=["Investments"],
    )
    at.session_state["unified_records"] = [_canonical_record()]
    at.run()
    assert not at.exception


def test_portfolio_tab_renders_with_pending_review_queue():
    at = AppTest.from_file("app.py", default_timeout=30)
    canon = _canonical_record()
    staged = UnifiedRecord(
        record_id=canon.record_id, asset_class=canon.asset_class, source_system=canon.source_system,
        identifier=canon.identifier, identifier_type=canon.identifier_type, name=canon.name,
        current_value=1500.0, account_name=canon.account_name,
    )
    new_staged = UnifiedRecord(
        record_id=make_record_id(SourceSystem.PERSONAL_SHEET, "Personal Sheet", "Fund B", AssetClass.MUTUAL_FUND),
        asset_class=AssetClass.MUTUAL_FUND, source_system=SourceSystem.PERSONAL_SHEET,
        identifier="Fund B", identifier_type="name", name="Fund B", current_value=500.0, account_name="Personal Sheet",
    )
    at.session_state["sheet_data"] = PersonalFinanceData(sheets_found=["Investments"])
    at.session_state["unified_records"] = [canon]
    at.session_state["pending_deltas"] = [
        Delta(canon.record_id, canon.name, canon.asset_class.value, "current_value", 1000.0, 1500.0, CHANGED),
        Delta(new_staged.record_id, new_staged.name, new_staged.asset_class.value, "*", None, "new record", NEW),
    ]
    at.session_state["pending_staged"] = {staged.record_id: staged, new_staged.record_id: new_staged}
    at.run()
    assert not at.exception

    # The "Apply accepted changes" button should exist and be clickable
    # without raising (accepts default-checked deltas).
    apply_buttons = [b for b in at.button if b.label == "Apply accepted changes"]
    assert len(apply_buttons) == 1
    apply_buttons[0].click().run()
    assert not at.exception
    assert len(at.session_state["unified_records"]) == 2  # Fund A updated + Fund B added
    assert at.session_state["pending_deltas"] == []
