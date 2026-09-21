"""Hi-Lo counts. An exhausted shoe has no defined true count."""

import math
from collections.abc import Iterable
from enum import StrEnum

from core.cards import Rank


class RoundingMode(StrEnum):
    NONE = "none"
    FLOOR = "floor"
    ROUND = "round"


def running_count(cards: Iterable[Rank]) -> int:
    return sum(card.hi_lo for card in cards)


def true_count(
    count: int,
    decks_remaining: float,
    rounding: RoundingMode = RoundingMode.NONE,
) -> float | int | None:
    """Round nearest ties away from zero; floor always rounds toward -infinity."""
    mode = RoundingMode(rounding)
    if not math.isfinite(decks_remaining) or decks_remaining < 0:
        raise ValueError("decks_remaining must be finite and nonnegative")
    if decks_remaining == 0:
        return None
    value = count / decks_remaining
    if mode is RoundingMode.FLOOR:
        return math.floor(value)
    if mode is RoundingMode.ROUND:
        return math.floor(value + 0.5) if value >= 0 else math.ceil(value - 0.5)
    return value
