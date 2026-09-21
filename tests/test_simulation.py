import random
from collections import Counter

import pytest

from core.cards import Rank
from core.rules import RuleConfig
from core.strategy import Strategy
from simulation.simulator import ShuffledShoe, play_round, simulate


class ScriptedShoe:
    def __init__(self, cards: str) -> None:
        self.cards = [Rank(card) for card in cards.split()]
        self.drawn = 0

    def draw(self) -> Rank:
        if self.drawn == len(self.cards):
            raise AssertionError("Unexpected extra draw")
        card = self.cards[self.drawn]
        self.drawn += 1
        return card


@pytest.mark.parametrize(
    "cards,profit,wagered",
    [
        ("A 9 K 7", 1.5, 1),              # Natural paid without a dealer draw.
        ("A A K Q", 0, 1),                 # Both naturals push.
        ("8 A 8 K", -1, 1),                # Peek ends round before a split.
        ("5 10 6 A", -1, 1),               # Peek before doubling.
        ("10 10 6 7 10", -1, 1),           # Player busts; dealer does not draw.
        ("10 6 Q 10 10", 1, 1),            # Dealer busts.
        ("10 10 8 8", 0, 1),               # Equal totals push.
        ("5 6 6 10 10 10", 2, 2),          # Double wins two units.
        ("5 10 6 9 2", -2, 2),             # Double loses two units.
        ("A 6 A 10 10 9 10", 2, 2),        # Split ace 21 pays 1:1.
        ("A 6 A 10 A 9 10", 2, 2),         # Split ace + ace gets no resplit or hit.
        ("8 6 8 10 3 10 2 10 10", 4, 4),  # Double both split hands, dealer bust.
    ],
)
def test_scripted_settlements(cards: str, profit: float, wagered: int) -> None:
    source = ScriptedShoe(cards)
    result = play_round(source, Strategy())
    assert result.profit == profit
    assert result.wagered == wagered
    assert source.drawn == len(source.cards)


def test_surrender_and_peek() -> None:
    strategy = Strategy(RuleConfig(surrender=True))
    result = play_round(ScriptedShoe("10 10 6 7"), strategy)
    assert result.profit == -0.5
    assert result.player_hands[0].surrendered
    assert play_round(ScriptedShoe("10 A 6 K"), strategy).profit == -1


def test_dealer_soft_seventeen() -> None:
    s17 = play_round(ScriptedShoe("10 A 8 6"), Strategy())
    h17 = play_round(ScriptedShoe("10 A 8 6 2"), Strategy(RuleConfig(dealer_hits_soft_17=True)))
    assert s17.dealer.total == 17 and s17.profit == 1
    assert h17.dealer.total == 19 and h17.profit == -1


def test_no_double_after_split() -> None:
    result = play_round(
        ScriptedShoe("8 6 8 10 3 10 2 10 10"),
        Strategy(RuleConfig(double_after_split=False)),
    )
    assert result.profit == 2 and result.wagered == 2


def test_split_limit_and_no_surrender_after_split() -> None:
    # Three resplits create four hands. At the cap, 8+8 must hit against 10.
    source = ScriptedShoe("8 10 8 7 8 8 8 3 10 10 10")
    result = play_round(source, Strategy(RuleConfig(surrender=True)))
    assert len(result.player_hands) == 4
    assert all(not item.surrendered for item in result.player_hands)
    assert all(item.hand.from_split for item in result.player_hands)
    assert result.profit == 4
    assert source.drawn == len(source.cards)


def test_shoe_inventory_cut_card_and_no_midround_shuffle() -> None:
    shoe = ShuffledShoe(RuleConfig(), random.Random(7))
    assert not shoe.needs_shuffle
    drawn = [shoe.draw() for _ in range(312)]
    assert Counter(drawn) == Counter({rank: 24 for rank in Rank})
    assert shoe.needs_shuffle
    with pytest.raises(RuntimeError, match="mid-round"):
        shoe.draw()
    shoe.shuffle()
    for _ in range(234):
        shoe.draw()
    assert shoe.needs_shuffle


def test_simulation_reproducible_and_accounted_per_initial_wager() -> None:
    result = simulate(hands=2_000, seed=41)
    assert result == simulate(hands=2_000, seed=41)
    assert result.house_edge == -result.total_profit / result.rounds
    assert result.total_wagered > result.rounds
    assert result.player_hands > result.rounds
    assert result.shoes > 1
    assert result.standard_error is not None and result.standard_error > 0
    assert result.confidence_interval_95 is not None
    assert result.confidence_interval_95[0] < result.house_edge < result.confidence_interval_95[1]
    assert result.baseline_check() == "insufficient_samples"


def test_tiny_sample_has_no_false_precision() -> None:
    result = simulate(hands=1)
    assert result.standard_error is None
    assert result.confidence_interval_95 is None
    assert result.round_standard_deviation is None


@pytest.mark.parametrize("hands", [0, -1, True, 2.5])
def test_invalid_sample_size(hands: int) -> None:
    with pytest.raises(ValueError):
        simulate(hands=hands)


@pytest.mark.slow
def test_million_round_house_edge() -> None:
    # Fixed seed, fixed sample size, no retries or favorable-seed selection.
    result = simulate(hands=1_000_000, seed=20260921)
    assert result.baseline_check() == "compatible"
    assert result.standard_error is not None and result.standard_error < 0.0015
    assert result.round_standard_deviation is not None
    assert 1.05 < result.round_standard_deviation < 1.25
