"""Finite-shoe, flat-bet simulation using the same core strategy as the trainer."""

import math
import random
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from core.cards import Rank
from core.hand import Hand
from core.rules import RuleConfig
from core.strategy import Action, Strategy


class CardSource(Protocol):
    def draw(self) -> Rank: ...


class ShuffledShoe:
    """Draw without replacement; never silently reshuffle during a round."""

    def __init__(self, rules: RuleConfig, rng: random.Random) -> None:
        self.rules = rules
        self.rng = rng
        self.cards: list[Rank] = []
        self.shuffle()
        # Each completed hand has hard total <= 30, even on a bust. Five
        # hands (four split hands plus dealer) therefore consume <= 150
        # hard-value points. The smallest cards give a conservative bound
        # on how many physical cards any round can possibly consume.
        hard_sum = 0
        self.round_reserve = 0
        for value in sorted(rank.hard_value for rank in self.cards):
            if hard_sum + value > 150:
                break
            hard_sum += value
            self.round_reserve += 1

    def shuffle(self) -> None:
        self.cards = [rank for rank in Rank for _ in range(self.rules.decks * 4)]
        self.rng.shuffle(self.cards)

    @property
    def needs_shuffle(self) -> bool:
        cut = math.floor(self.rules.decks * 52 * (1 - self.rules.penetration))
        return len(self.cards) <= max(cut, self.round_reserve)

    def draw(self) -> Rank:
        if not self.cards:
            raise RuntimeError("Shoe exhausted mid-round; cannot reshuffle a live hand")
        return self.cards.pop()


@dataclass(frozen=True)
class PlayedHand:
    hand: Hand
    wager: int = 1
    surrendered: bool = False


@dataclass(frozen=True)
class RoundResult:
    profit: float
    wagered: int
    player_hands: tuple[PlayedHand, ...]
    dealer: Hand


def play_round(source: CardSource, strategy: Strategy) -> RoundResult:
    """One initial one-unit wager; returned profit includes split/double wagers.

    Fixed rules: American peek, natural pays 3:2, at most four player hands,
    no resplitting aces, one card to each split ace, no insurance, late surrender.
    """
    player_first, dealer_up = source.draw(), source.draw()
    player = Hand((player_first, source.draw()))
    dealer = Hand((dealer_up, source.draw()))
    if dealer.is_blackjack:
        return RoundResult(0.0 if player.is_blackjack else -1.0, 1, (PlayedHand(player),), dealer)
    if player.is_blackjack:
        return RoundResult(1.5, 1, (PlayedHand(player),), dealer)

    pending = [player]
    finished: list[PlayedHand] = []
    hand_count = 1
    while pending:
        current = pending.pop()
        if len(current.cards) == 1:
            current = current.add(source.draw())
            if current.cards[0] is Rank.ACE:
                finished.append(PlayedHand(current))
                continue
        while True:
            action = strategy.recommend(current, dealer_up, can_split=hand_count < 4)
            if action is None or action is Action.STAND:
                finished.append(PlayedHand(current))
                break
            if action is Action.HIT:
                current = current.add(source.draw())
            elif action is Action.DOUBLE:
                finished.append(PlayedHand(current.add(source.draw()), wager=2))
                break
            elif action is Action.SURRENDER:
                finished.append(PlayedHand(current, surrendered=True))
                break
            elif action is Action.SPLIT:
                hand_count += 1
                pending.append(Hand((current.cards[1],), from_split=True))
                pending.append(Hand((current.cards[0],), from_split=True))
                break

    if any(not item.surrendered and not item.hand.is_bust for item in finished):
        while dealer.total < 17 or (
            strategy.rules.dealer_hits_soft_17 and dealer.total == 17 and dealer.is_soft
        ):
            dealer = dealer.add(source.draw())

    profit = 0.0
    for item in finished:
        if item.surrendered:
            profit -= 0.5
        elif item.hand.is_bust:
            profit -= item.wager
        elif dealer.is_bust or item.hand.total > dealer.total:
            profit += item.wager
        elif item.hand.total < dealer.total:
            profit -= item.wager
    return RoundResult(profit, sum(item.wager for item in finished), tuple(finished), dealer)


@dataclass(frozen=True)
class SimulationResult:
    rules: RuleConfig
    seed: int
    rounds: int
    player_hands: int
    shoes: int
    total_profit: float
    total_wagered: int
    house_edge: float
    standard_error: float | None
    confidence_interval_95: tuple[float, float] | None
    round_standard_deviation: float | None

    def baseline_check(self) -> str:
        """Statistical compatibility check, not proof that the edge is in range."""
        if self.rules != RuleConfig():
            return "not_applicable"
        if self.rounds < 1_000_000 or self.confidence_interval_95 is None:
            return "insufficient_samples"
        low, high = self.confidence_interval_95
        return "compatible" if low <= 0.006 and high >= 0.004 else "outside_expected_range"


def simulate(
    rules: RuleConfig = RuleConfig(),
    hands: int = 10_000,
    seed: int = 20260921,
    progress: Callable[[int], None] | None = None,
) -> SimulationResult:
    if type(hands) is not int or hands < 1:
        raise ValueError("hands must be a positive integer (initial rounds, before splits)")
    strategy = Strategy(rules)
    shoe = ShuffledShoe(rules, random.Random(seed))
    profit = squared_profit = 0.0
    wagered = player_hands = 0
    cluster_profit = 0.0
    cluster_rounds = 0
    clusters: list[tuple[float, int]] = []
    for index in range(hands):
        if shoe.needs_shuffle:
            clusters.append((cluster_profit, cluster_rounds))
            cluster_profit, cluster_rounds = 0.0, 0
            shoe.shuffle()
        result = play_round(shoe, strategy)
        profit += result.profit
        squared_profit += result.profit * result.profit
        wagered += result.wagered
        player_hands += len(result.player_hands)
        cluster_profit += result.profit
        cluster_rounds += 1
        if progress is not None and (index + 1) % 100_000 == 0:
            progress(index + 1)
    clusters.append((cluster_profit, cluster_rounds))
    mean = profit / hands
    standard_error = None
    interval = None
    # Shoe-cluster standard errors allow correlation between rounds in a shoe.
    if len(clusters) > 1:
        residual_squares = sum((net - mean * size) ** 2 for net, size in clusters)
        standard_error = math.sqrt(len(clusters) / (len(clusters) - 1) * residual_squares) / hands
        interval = (-mean - 1.96 * standard_error, -mean + 1.96 * standard_error)
    deviation = math.sqrt(max(0, (squared_profit - profit * profit / hands) / (hands - 1))) if hands > 1 else None
    return SimulationResult(
        rules, seed, hands, player_hands, len(clusters), profit, wagered,
        -mean, standard_error, interval, deviation,
    )
