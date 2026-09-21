"""Finite shoe inventory; exposed cards are removed without modeling suits."""

from collections import Counter
from collections.abc import Iterable

from core.cards import Rank


class Shoe:
    def __init__(self, decks: int = 6, seen: Iterable[Rank] = ()) -> None:
        if isinstance(decks, bool) or not isinstance(decks, int) or decks < 1:
            raise ValueError("decks must be a positive integer")
        self._decks = decks
        self._seen: Counter[Rank] = Counter()
        for rank in seen:
            self.observe(rank)

    @property
    def decks(self) -> int:
        return self._decks

    @property
    def cards_seen(self) -> int:
        return self._seen.total()

    @property
    def cards_remaining(self) -> int:
        return self.decks * 52 - self.cards_seen

    @property
    def decks_remaining(self) -> float:
        return self.cards_remaining / 52

    def remaining(self, rank: Rank) -> int:
        return self.decks * 4 - self._seen[rank]

    def observe(self, rank: Rank) -> None:
        if not isinstance(rank, Rank):
            raise TypeError("rank must be a Rank")
        if self.remaining(rank) == 0:
            raise ValueError(f"No {rank} cards remain in the shoe")
        self._seen[rank] += 1
