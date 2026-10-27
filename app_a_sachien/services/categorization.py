"""Merchant categorization using transparent, editable rules."""
from __future__ import annotations

import fnmatch
from sqlalchemy import select
from sqlalchemy.orm import Session

from models import CategoryRule

# Seed rules applied when the rule table is empty (all editable via API/UI).
DEFAULT_RULES: list[tuple[str, str]] = [
    ("netflix", "Subscriptions"),
    ("amazon prime", "Subscriptions"),
    ("spotify", "Subscriptions"),
    ("youtube premium", "Subscriptions"),
    ("icici bank", "Bills"),
    ("electricity", "Bills"),
    ("water supply", "Bills"),
    ("airtel", "Bills"),
    ("jio", "Bills"),
    ("swiggy", "Food"),
    ("zomato", "Food"),
    ("dunkin", "Food"),
    ("uber", "Travel"),
    ("ola", "Travel"),
    ("indian railways", "Travel"),
    ("irctc", "Travel"),
    ("petrol", "Travel"),
    ("movie", "Entertainment"),
    ("pvr", "Entertainment"),
    ("inox", "Entertainment"),
    ("flipkart", "Shopping"),
    ("myntra", "Shopping"),
]


def ensure_default_rules(db: Session) -> None:
    if db.scalar(select(CategoryRule).limit(1)) is None:
        for pattern, category in DEFAULT_RULES:
            db.add(CategoryRule(pattern=pattern, category=category, priority=50))
        db.commit()


def categorize_merchant(db: Session, merchant: str) -> str:
    """Return best-matching category for a merchant name, else 'Other'.

    Rules use simple wildcard/glob matching (transparent and editable).
    Higher priority wins; longer pattern wins on ties.
    """
    ensure_default_rules(db)
    name = merchant.strip().lower()
    rules = db.scalars(
        select(CategoryRule).order_by(
            CategoryRule.priority.desc(), CategoryRule.pattern.desc()
        )
    ).all()
    for rule in rules:
        pattern = rule.pattern.strip().lower()
        if "*" in pattern or "?" in pattern:
            if fnmatch.fnmatch(name, pattern):
                return rule.category
        elif pattern in name:
            return rule.category
    return "Other"
