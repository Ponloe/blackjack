"""Expected decisions below are independent examples, not echoes of the JSON."""

import json
from dataclasses import replace
from itertools import product
from pathlib import Path

import pytest

from core.cards import Rank
from core.hand import Hand
from core.rules import RuleConfig
from core.strategy import DEFAULT_TABLE_PATH, Action, Strategy


def make_hand(cards: str, from_split: bool = False) -> Hand:
    return Hand(tuple(Rank(card) for card in cards.split()), from_split)


@pytest.fixture
def strategy() -> Strategy:
    return Strategy()


@pytest.mark.parametrize(
    "cards,dealer,expected",
    [
        ("10 2", "3", Action.HIT), ("10 2", "4", Action.STAND),
        ("10 6", "10", Action.HIT), ("10 7", "A", Action.STAND),
        ("4 5", "2", Action.HIT), ("4 5", "3", Action.DOUBLE),
        ("5 5", "9", Action.DOUBLE), ("5 5", "10", Action.HIT),
        ("5 6", "10", Action.DOUBLE), ("5 6", "A", Action.HIT),
        ("A 2", "4", Action.HIT), ("A 2", "5", Action.DOUBLE),
        ("A 4", "4", Action.DOUBLE), ("A 6", "3", Action.DOUBLE),
        ("A 7", "2", Action.STAND), ("A 7", "3", Action.DOUBLE),
        ("A 7", "8", Action.STAND), ("A 7", "9", Action.HIT),
        ("A 7", "A", Action.HIT), ("A 8", "6", Action.STAND),
        ("A A", "A", Action.SPLIT), ("8 8", "10", Action.SPLIT),
        ("2 2", "2", Action.SPLIT), ("3 3", "3", Action.SPLIT),
        ("4 4", "4", Action.HIT), ("4 4", "5", Action.SPLIT),
        ("6 6", "2", Action.SPLIT), ("7 7", "7", Action.SPLIT),
        ("7 7", "8", Action.HIT), ("9 9", "7", Action.STAND),
        ("9 9", "8", Action.SPLIT), ("9 9", "9", Action.SPLIT),
        ("9 9", "10", Action.STAND), ("J K", "6", Action.STAND),
    ],
)
def test_known_s17_decisions(strategy: Strategy, cards: str, dealer: str, expected: Action) -> None:
    assert strategy.recommend(make_hand(cards), Rank(dealer)) is expected


@pytest.mark.parametrize("h17,das,surrender", list(product((False, True), repeat=3)))
def test_rule_variants(h17: bool, das: bool, surrender: bool) -> None:
    strategy = Strategy(RuleConfig(dealer_hits_soft_17=h17, double_after_split=das, surrender=surrender))
    assert strategy.recommend(make_hand("5 6"), Rank.ACE) is (Action.DOUBLE if h17 else Action.HIT)
    assert strategy.recommend(make_hand("A 7"), Rank.TWO) is (Action.DOUBLE if h17 else Action.STAND)
    assert strategy.recommend(make_hand("A 8"), Rank.SIX) is (Action.DOUBLE if h17 else Action.STAND)
    assert strategy.recommend(make_hand("4 4"), Rank.FIVE) is (Action.SPLIT if das else Action.HIT)
    assert strategy.recommend(make_hand("6 6"), Rank.TWO) is (Action.SPLIT if das else Action.HIT)
    assert strategy.recommend(make_hand("10 6"), Rank.TEN) is (Action.SURRENDER if surrender else Action.HIT)
    assert strategy.recommend(make_hand("8 8"), Rank.TEN) is Action.SPLIT
    assert strategy.recommend(make_hand("8 8"), Rank.ACE) is (Action.SURRENDER if h17 and surrender else Action.SPLIT)
    assert strategy.recommend(make_hand("10 7"), Rank.ACE) is (Action.SURRENDER if h17 and surrender else Action.STAND)


def test_legality_and_fallbacks(strategy: Strategy) -> None:
    assert strategy.recommend(make_hand("A 7"), Rank.THREE, can_double=False) is Action.STAND
    assert strategy.recommend(make_hand("5 6"), Rank.SIX, can_double=False) is Action.HIT
    assert strategy.recommend(make_hand("8 8"), Rank.TEN, can_split=False) is Action.HIT
    assert strategy.recommend(make_hand("A A"), Rank.SIX, can_split=False) is Action.DOUBLE
    assert strategy.recommend(make_hand("A A"), Rank.FIVE, can_split=False) is Action.HIT
    assert strategy.recommend(make_hand("2 4 5"), Rank.SIX) is Action.HIT
    assert strategy.recommend(make_hand("A 2 5"), Rank.THREE) is Action.STAND
    no_das = Strategy(RuleConfig(double_after_split=False))
    assert no_das.recommend(make_hand("5 6", True), Rank.SIX) is Action.HIT
    assert strategy.recommend(make_hand("5 6", True), Rank.SIX) is Action.DOUBLE
    surrender = Strategy(RuleConfig(surrender=True, dealer_hits_soft_17=True))
    assert surrender.recommend(make_hand("10 6"), Rank.TEN, can_surrender=False) is Action.HIT
    assert surrender.recommend(make_hand("8 8", True), Rank.ACE) is Action.SPLIT
    assert surrender.recommend(make_hand("8 8", True), Rank.ACE, can_split=False) is Action.HIT
    assert surrender.recommend(make_hand("10 7"), Rank.ACE, can_surrender=False) is Action.STAND
    assert surrender.recommend(make_hand("2 4 10"), Rank.TEN) is Action.HIT


@pytest.mark.parametrize("cards", ["", "A", "A K", "10 5 6", "10 K 2"])
def test_incomplete_or_finished(strategy: Strategy, cards: str) -> None:
    assert strategy.recommend(make_hand(cards), Rank.SIX) is None


@pytest.mark.parametrize("decks", [4, 5, 6, 7, 8])
def test_supported_decks(decks: int) -> None:
    assert Strategy(RuleConfig(decks=decks)).recommend(make_hand("8 8"), Rank.ACE) is Action.SPLIT


@pytest.mark.parametrize("decks", [0, 1, 2, 3, 9, True, 6.5])
def test_unsupported_decks(decks: int) -> None:
    with pytest.raises(ValueError, match="4–8"):
        RuleConfig(decks=decks)


@pytest.mark.parametrize("penetration", [0, -1, 0.99, float("nan"), float("inf"), True])
def test_invalid_penetration(penetration: float) -> None:
    with pytest.raises(ValueError, match="penetration"):
        RuleConfig(penetration=penetration)


@pytest.mark.parametrize("name", ["dealer_hits_soft_17", "double_after_split", "surrender"])
def test_rule_flags_require_booleans(name: str) -> None:
    with pytest.raises(ValueError, match="boolean"):
        replace(RuleConfig(), **{name: "false"})


def test_malformed_table_rejected(tmp_path: Path) -> None:
    data = json.loads(DEFAULT_TABLE_PATH.read_text())
    del data["rule_sets"]["4-8/S17/DAS/NS"]["tables"]["hard"]["12"]
    path = tmp_path / "strategy.json"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="Incomplete hard"):
        Strategy(path=path)


def test_inheritance_cycle_rejected(tmp_path: Path) -> None:
    data = json.loads(DEFAULT_TABLE_PATH.read_text())
    data["rule_sets"]["4-8/S17/DAS/NS"]["extends"] = "4-8/S17/DAS/NS"
    path = tmp_path / "strategy.json"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="cycle"):
        Strategy(path=path)
