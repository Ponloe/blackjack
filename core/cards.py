"""Ranks and card values; suits do not affect blackjack evaluation."""

from enum import StrEnum


class Rank(StrEnum):
    ACE = "A"
    TWO = "2"
    THREE = "3"
    FOUR = "4"
    FIVE = "5"
    SIX = "6"
    SEVEN = "7"
    EIGHT = "8"
    NINE = "9"
    TEN = "10"
    JACK = "J"
    QUEEN = "Q"
    KING = "K"

    @property
    def hard_value(self) -> int:
        if self is Rank.ACE:
            return 1
        if self in (Rank.TEN, Rank.JACK, Rank.QUEEN, Rank.KING):
            return 10
        return int(self.value)

    @property
    def hi_lo(self) -> int:
        if 2 <= self.hard_value <= 6:
            return 1
        if 7 <= self.hard_value <= 9:
            return 0
        return -1
