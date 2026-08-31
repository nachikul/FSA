from datetime import date

import pandas as pd

from src.adapters.from_indmoney import from_indmoney
from src.adapters.from_sheet import from_investment_items
from src.adapters.from_statement import from_statement
from src.core.unified import AssetClass, SourceSystem
from src.models import Statement, Transaction
from src.sources.indmoney import IndmoneyPortfolio
from src.sources.personal_sheet import InvestmentItem


def test_from_statement_uses_closing_balance():
    stmt = Statement(
        bank="HDFC",
        account_number="XX1234",
        opening_balance=1000.0,
        closing_balance=5000.0,
        period_end=date(2026, 8, 1),
        transactions=[Transaction(date=date(2026, 8, 1), narration="x", credit=4000.0)],
        source_file="hdfc.pdf",
    )
    records = from_statement(stmt)
    assert len(records) == 1
    rec = records[0]
    assert rec.asset_class == AssetClass.BANK_CASH
    assert rec.current_value == 5000.0
    assert rec.account_name == "XX1234"


def test_from_statement_skips_when_no_closing_balance():
    stmt = Statement(bank="GENERIC", closing_balance=None, source_file="unknown.pdf")
    assert from_statement(stmt) == []


def test_from_investment_items_maps_sections():
    items = [
        InvestmentItem(section="Mutual Funds", subsection=None, name="Fund A", amount=1000.0, current_value=1200.0, monthly_value=None, details="Folio123"),
        InvestmentItem(section="Fixed Deposits", subsection=None, name="FD @ HDFC", amount=50000.0, current_value=None, monthly_value=None, details=None),
        InvestmentItem(section="Liabilities", subsection="Loans", name="Home Loan", amount=2000000.0, current_value=None, monthly_value=None, details=None),
    ]
    records = from_investment_items(items)
    by_name = {r.name: r for r in records}

    assert by_name["Fund A"].asset_class == AssetClass.MUTUAL_FUND
    assert by_name["Fund A"].current_value == 1200.0  # prefers current_value over amount
    assert by_name["Fund A"].identifier == "Folio123"

    assert by_name["FD @ HDFC"].asset_class == AssetClass.FIXED_DEPOSIT
    assert by_name["FD @ HDFC"].current_value == 50000.0  # falls back to amount

    assert by_name["Home Loan"].asset_class == AssetClass.LIABILITY


def test_from_investment_items_skips_items_with_no_value():
    items = [InvestmentItem(section="Others", subsection=None, name="Unknown", amount=None, current_value=None, monthly_value=None, details=None)]
    assert from_investment_items(items) == []


def test_from_indmoney_reads_known_columns():
    portfolio = IndmoneyPortfolio()
    portfolio.holdings = {
        "MF": pd.DataFrame([{"investment": "HDFC Flexicap", "market_value": 12000.0, "invested_amount": 10000.0, "units": 100.0}]),
        "IND_STOCK": pd.DataFrame([{"investment": "TCS", "market_value": 30000.0, "isin": "INE467B01029"}]),
    }
    records = from_indmoney(portfolio)
    assert len(records) == 2

    mf = next(r for r in records if r.name == "HDFC Flexicap")
    assert mf.asset_class == AssetClass.MUTUAL_FUND
    assert mf.current_value == 12000.0
    assert mf.cost_basis == 10000.0
    assert mf.quantity == 100.0

    stock = next(r for r in records if r.name == "TCS")
    assert stock.asset_class == AssetClass.EQUITY
    assert stock.identifier == "INE467B01029"
    assert stock.identifier_type == "isin"


def test_from_indmoney_skips_rows_missing_name_or_value():
    portfolio = IndmoneyPortfolio()
    portfolio.holdings = {"MF": pd.DataFrame([{"market_value": 12000.0}])}  # no name column
    assert from_indmoney(portfolio) == []


def test_from_indmoney_ignores_empty_holdings():
    portfolio = IndmoneyPortfolio()
    portfolio.holdings = {"FD": pd.DataFrame()}
    assert from_indmoney(portfolio) == []
