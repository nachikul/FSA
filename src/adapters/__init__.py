"""Thin, pure functions that project the app's EXISTING per-source objects
(Statement, InvestmentItem, IndmoneyPortfolio) into UnifiedRecord. Nothing
in src/models.py, src/sources/personal_sheet.py, or src/sources/indmoney.py
changes — every existing tab keeps reading its original object exactly as
it does today. This package is what's new."""
