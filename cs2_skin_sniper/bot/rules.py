"""Движок сопоставления: подходит ли лот под правило."""

from __future__ import annotations

from .models import Listing, Rule


def matches(rule: Rule, listing: Listing) -> bool:
    if rule.name_query.lower() not in listing.name.lower():
        return False
    if listing.price > rule.max_price:
        return False
    if rule.min_float is not None:
        if listing.float_value is None or listing.float_value < rule.min_float:
            return False
    if rule.max_float is not None:
        if listing.float_value is None or listing.float_value > rule.max_float:
            return False
    if rule.seeds:
        if listing.paint_seed is None or listing.paint_seed not in rule.seeds:
            return False
    if rule.stickers:
        low = [s.lower() for s in listing.stickers]
        if not any(any(kw.lower() in s for s in low) for kw in rule.stickers):
            return False
    if rule.min_discount > 0:
        d = listing.discount()
        if d is None or d < rule.min_discount:
            return False
    return True


def matching_rules(rules: list[Rule], listing: Listing) -> list[Rule]:
    return [r for r in rules if matches(r, listing)]
