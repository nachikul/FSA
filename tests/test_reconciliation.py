from src.core.unified import AssetClass, SourceSystem, UnifiedRecord, make_record_id
from src.reconciliation.delta import CHANGED, NEW, POSSIBLY_STALE, compute_deltas
from src.reconciliation.identity import match
from src.reconciliation.merge_engine import apply


def _record(name, value, account="ACC1", asset_class=AssetClass.MUTUAL_FUND, source=SourceSystem.PERSONAL_SHEET, identifier=None):
    identifier = identifier or name
    return UnifiedRecord(
        record_id=make_record_id(source, account, identifier, asset_class),
        asset_class=asset_class,
        source_system=source,
        identifier=identifier,
        identifier_type="name",
        name=name,
        current_value=value,
        account_name=account,
    )


def test_match_exact_by_record_id():
    canon = _record("Fund A", 1000.0)
    staged = _record("Fund A", 1200.0)  # same identity fields -> same record_id
    matches = match([staged], [canon])
    assert matches[staged.record_id] == canon.record_id


def test_match_fuzzy_fallback_within_threshold():
    canon = _record("HDFC Flexicap Fund", 1000.0, identifier="Folio-1")
    staged = _record("HDFC Flexicap  Fund", 1200.0, identifier="Folio-1-typo")  # different identifier, near-identical name
    matches = match([staged], [canon])
    assert matches[staged.record_id] == canon.record_id


def test_match_returns_none_below_threshold():
    canon = _record("HDFC Flexicap Fund", 1000.0, identifier="Folio-1")
    staged = _record("Totally Different Fund", 1200.0, identifier="Folio-2")
    matches = match([staged], [canon])
    assert matches[staged.record_id] is None


def test_match_does_not_cross_source_or_account():
    canon = _record("Fund A", 1000.0, account="ACC1", source=SourceSystem.PERSONAL_SHEET, identifier="x")
    staged = _record("Fund A", 1000.0, account="ACC1", source=SourceSystem.INDMONEY, identifier="y")
    matches = match([staged], [canon])
    assert matches[staged.record_id] is None


def test_compute_deltas_flags_new_record():
    staged = [_record("Fund A", 1000.0)]
    deltas = compute_deltas(staged, canonical=[], matches={staged[0].record_id: None})
    assert len(deltas) == 1
    assert deltas[0].status == NEW


def test_compute_deltas_flags_changed_value():
    canon = _record("Fund A", 1000.0)
    staged = _record("Fund A", 1500.0)  # matches by record_id since identity fields are unchanged
    deltas = compute_deltas([staged], [canon], matches={staged.record_id: canon.record_id})
    assert len(deltas) == 1
    assert deltas[0].status == CHANGED
    assert deltas[0].field == "current_value"
    assert deltas[0].old_value == 1000.0
    assert deltas[0].new_value == 1500.0


def test_compute_deltas_flags_possibly_stale_within_same_scope():
    canon = _record("Fund A", 1000.0, account="ACC1")
    other_staged = _record("Fund B", 500.0, account="ACC1")  # same scope, different record — Fund A absent
    deltas = compute_deltas([other_staged], [canon], matches={other_staged.record_id: None})
    statuses = {d.status for d in deltas}
    assert NEW in statuses
    assert POSSIBLY_STALE in statuses


def test_compute_deltas_does_not_flag_stale_outside_upload_scope():
    canon = _record("Fund A", 1000.0, account="ACC1")
    unrelated_staged = _record("Fund B", 500.0, account="ACC2")  # different account scope entirely
    deltas = compute_deltas([unrelated_staged], [canon], matches={unrelated_staged.record_id: None})
    assert all(d.status != POSSIBLY_STALE for d in deltas)


def test_apply_new_record_adds_to_canonical():
    staged = _record("Fund A", 1000.0)
    delta = compute_deltas([staged], [], {staged.record_id: None})[0]
    result = apply([delta], {staged.record_id: staged}, [])
    assert len(result) == 1
    assert result[0].name == "Fund A"


def test_apply_changed_updates_field_in_place_on_new_list():
    canon = _record("Fund A", 1000.0)
    staged = _record("Fund A", 1500.0)
    delta = compute_deltas([staged], [canon], {staged.record_id: canon.record_id})[0]
    result = apply([delta], {staged.record_id: staged}, [canon])
    assert result[0].current_value == 1500.0


def test_apply_possibly_stale_removes_when_accepted():
    canon = _record("Fund A", 1000.0)
    delta_list = compute_deltas(
        staged=[_record("Fund B", 500.0, account=canon.account_name)],
        canonical=[canon],
        matches={},
    )
    stale = next(d for d in delta_list if d.status == POSSIBLY_STALE)
    result = apply([stale], {}, [canon])
    assert result == []


def test_apply_rejects_deltas_not_passed_in():
    canon = _record("Fund A", 1000.0)
    staged = _record("Fund A", 1500.0)
    delta = compute_deltas([staged], [canon], {staged.record_id: canon.record_id})[0]
    # Not accepted -> not passed to apply() -> canonical unchanged
    result = apply([], {staged.record_id: staged}, [canon])
    assert result[0].current_value == 1000.0
