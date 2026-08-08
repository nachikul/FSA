"""Bundles every data source the Ask AI tools can query, so app.py only
builds and passes one object regardless of which sources are loaded."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd

from ..sources.indmoney import IndmoneyPortfolio
from ..sources.personal_sheet import PersonalFinanceData


@dataclass
class AppContext:
    transactions: pd.DataFrame
    sheet: Optional[PersonalFinanceData] = None
    portfolio: Optional[IndmoneyPortfolio] = None
