"""Immutable hand evaluation, including split-hand natural eligibility."""

from dataclasses import dataclass

from core.cards import Rank


@dataclass(frozen=True)
class Hand:
    cards: tuple[Rank, ...] = ()
    from_split: bool = False

    @property
    def hard_total(self) -> int:
        return sum(card.hard_value for card in self.cards)

    @property
    def is_soft(self) -> bool:
        return Rank.ACE in self.cards and self.hard_total + 10 <= 21

    @property
    def total(self) -> int:
        return self.hard_total + (10 if self.is_soft else 0)

    @property
    def is_blackjack(self) -> bool:
        return len(self.cards) == 2 and self.total == 21 and not self.from_split

    @property
    def is_bust(self) -> bool:
        return self.total > 21

    @property
    def is_pair(self) -> bool:
        """Equal blackjack values can split, including mixed ten-value ranks."""
        return len(self.cards) == 2 and self.cards[0].hard_value == self.cards[1].hard_value

    def add(self, rank: Rank) -> "Hand":
        return Hand(self.cards + (rank,), from_split=self.from_split)
