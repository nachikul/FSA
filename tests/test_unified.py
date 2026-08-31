from src.core.unified import AssetClass, SourceSystem, UnifiedRecord, make_record_id


def test_make_record_id_is_deterministic():
    a = make_record_id(SourceSystem.BANK_STATEMENT, "1234", "1234", AssetClass.BANK_CASH)
    b = make_record_id(SourceSystem.BANK_STATEMENT, "1234", "1234", AssetClass.BANK_CASH)
    assert a == b


def test_make_record_id_is_case_and_whitespace_insensitive():
    a = make_record_id(SourceSystem.PERSONAL_SHEET, "Personal Sheet", "HDFC Flexicap", AssetClass.MUTUAL_FUND)
    b = make_record_id(SourceSystem.PERSONAL_SHEET, " personal sheet ", "hdfc flexicap", AssetClass.MUTUAL_FUND)
    assert a == b


def test_make_record_id_differs_by_asset_class():
    a = make_record_id(SourceSystem.INDMONEY, "INDmoney", "INE123", AssetClass.EQUITY)
    b = make_record_id(SourceSystem.INDMONEY, "INDmoney", "INE123", AssetClass.MUTUAL_FUND)
    assert a != b


def test_unified_record_defaults():
    rec = UnifiedRecord(
        record_id="abc",
        asset_class=AssetClass.GOLD,
        source_system=SourceSystem.GOLD_STATEMENT,
        identifier="GOLD-1",
        identifier_type="name",
        name="Digital Gold",
    )
    assert rec.quantity == 1.0
    assert rec.current_value == 0.0
    assert rec.link_group is None
    assert rec.extra == {}
