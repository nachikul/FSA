"""Keyword-based transaction categorization, driven by an editable YAML
ruleset (see rules_default.yaml) so users can tune it to their own spending
without touching code."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import pandas as pd
import yaml

from .parsers.utils import normalize_for_matching

DEFAULT_RULES_PATH = Path(__file__).parent / "rules_default.yaml"
UNCATEGORIZED = "Uncategorized"


def load_default_rules() -> str:
    return DEFAULT_RULES_PATH.read_text()


def parse_rules(yaml_text: str) -> list[dict]:
    data = yaml.safe_load(yaml_text) or {}
    categories = data.get("categories", [])
    compiled = []
    for cat in categories:
        name = cat.get("name")
        keywords = [normalize_for_matching(k) for k in cat.get("keywords", [])]
        direction = cat.get("direction")  # "credit" | "debit" | None
        if name and keywords:
            compiled.append({"name": name, "keywords": keywords, "direction": direction})
    return compiled


def categorize_one(narration: str, direction: str, rules: list[dict]) -> str:
    normalized = normalize_for_matching(narration)
    for rule in rules:
        if rule["direction"] and rule["direction"] != direction:
            continue
        if any(kw in normalized for kw in rule["keywords"]):
            return rule["name"]
    return UNCATEGORIZED


def categorize_dataframe(df: pd.DataFrame, rules: list[dict]) -> pd.DataFrame:
    if df.empty:
        return df
    df = df.copy()
    df["category"] = [
        categorize_one(narration, direction, rules)
        for narration, direction in zip(df["narration"], df["direction"])
    ]
    return df


def validate_rules_yaml(yaml_text: str) -> Optional[str]:
    """Returns an error message if the YAML is invalid/empty, else None."""
    try:
        rules = parse_rules(yaml_text)
    except yaml.YAMLError as exc:
        return f"YAML syntax error: {exc}"
    if not rules:
        return "No valid categories found — check the structure against the default rules."
    return None
