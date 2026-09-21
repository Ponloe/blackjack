from itertools import product

import pytest
from hypothesis import given, strategies as st

from core.cards import Rank
from core.counting import RoundingMode, running_count, true_count
from core.hand import Hand
from core.shoe import Shoe


def hand(*cards: str, from_split: bool = False) -> Hand:
    return Hand(tuple(Rank(card) for card in cards), from_split=from_split)


@pytest.mark.parametrize(
    "cards,total,soft,bust",
    [
        ((), 0, False, False),
        (("A",), 11, True, False),
        (("A", "A"), 12, True, False),
        (("A", "6"), 17, True, False),
        (("A", "6", "10"), 17, False, False),
        (("A", "A", "9"), 21, True, False),
        (("A", "A", "9", "K"), 21, False, False),
        (("K", "Q", "2"), 22, False, True),
        (("A", "K", "Q", "2"), 23, False, True),
    ],
)
def test_totals(cards: tuple[str, ...], total: int, soft: bool, bust: bool) -> None:
    evaluated = hand(*cards)
    assert (evaluated.total, evaluated.is_soft, evaluated.is_bust) == (total, soft, bust)


def test_blackjack_and_pairs() -> None:
    assert hand("A", "K").is_blackjack
    assert not hand("A", "K", from_split=True).is_blackjack
    assert not hand("7", "7", "7").is_blackjack
    assert hand("8", "8").is_pair
    assert hand("J", "K").is_pair
    assert hand("A", "A").is_pair
    assert not hand("8", "9").is_pair
    assert not hand("8").is_pair
    assert not hand().is_pair


def test_add_preserves_original_and_split_status() -> None:
    original = hand("A", from_split=True)
    updated = original.add(Rank.KING)
    assert original.cards == (Rank.ACE,)
    assert updated.total == 21
    assert not updated.is_blackjack


@pytest.mark.parametrize("rank,expected", list(zip(Rank, [-1, 1, 1, 1, 1, 1, 0, 0, 0, -1, -1, -1, -1])))
def test_hi_lo(rank: Rank, expected: int) -> None:
    assert rank.hi_lo == expected


def test_running_count() -> None:
    assert running_count([]) == 0
    assert running_count([Rank.TWO, Rank.THREE, Rank.KING, Rank.SEVEN]) == 1


@pytest.mark.parametrize("count,expected", [(5, 3), (-5, -3), (4, 2), (-4, -2)])
def test_nearest_rounding(count: int, expected: int) -> None:
    assert true_count(count, 2, RoundingMode.ROUND) == expected


def test_true_count() -> None:
    assert true_count(5, 2) == 2.5
    assert true_count(-5, 2, RoundingMode.FLOOR) == -3
    assert true_count(5, 2, RoundingMode.FLOOR) == 2
    assert true_count(1, 0.25) == 4
    assert true_count(0, 0) is None


@pytest.mark.parametrize("remaining", [-1, float("nan"), float("inf")])
def test_invalid_decks_remaining(remaining: float) -> None:
    with pytest.raises(ValueError):
        true_count(1, remaining)


def test_shoe_estimation_and_inventory() -> None:
    shoe = Shoe(6, [Rank.TWO] * 13)
    assert shoe.cards_seen == 13
    assert shoe.cards_remaining == 299
    assert shoe.decks_remaining == 5.75
    assert shoe.remaining(Rank.TWO) == 11
    exhausted_rank = Shoe(1, [Rank.ACE] * 4)
    with pytest.raises(ValueError):
        exhausted_rank.observe(Rank.ACE)
    assert exhausted_rank.cards_seen == 4


@pytest.mark.parametrize("decks", [0, -1, True, 1.5])
def test_invalid_shoe_size(decks: int) -> None:
    with pytest.raises(ValueError):
        Shoe(decks)


@pytest.mark.parametrize("decks", [1, 2, 6, 8])
def test_full_shoe_count_invariant(decks: int) -> None:
    cards = [rank for rank in Rank for _ in range(4 * decks)]
    shoe = Shoe(decks, cards)
    assert running_count(cards) == 0
    assert shoe.cards_remaining == 0
    assert shoe.decks_remaining == 0


@given(st.lists(st.sampled_from(list(Rank)), max_size=10))
def test_hand_matches_exhaustive_ace_assignments(cards: list[Rank]) -> None:
    # Independent oracle enumerates every possible ace value.
    choices = [(1, 11) if rank is Rank.ACE else (rank.hard_value,) for rank in cards]
    totals = [sum(values) for values in product(*choices)]
    legal = [total for total in totals if total <= 21]
    expected = max(legal) if legal else min(totals)
    evaluated = Hand(tuple(cards))
    assert evaluated.total == expected
    assert evaluated.is_soft == (expected > min(totals))
    assert evaluated.is_bust == (min(totals) > 21)
    assert Hand(tuple(reversed(cards))).total == expected
