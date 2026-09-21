from dataclasses import replace
from pathlib import Path

import pytest
from hypothesis import given, strategies as st

from app.session import Session
from core.cards import Rank
from core.counting import RoundingMode
from core.events import CardDealt, NewHand, NewShoe, RemoveCard, Source, replay
from core.rules import RuleConfig


def test_rounds_shoes_corrections_and_undo() -> None:
    session = Session(":memory:")
    card = CardDealt(Rank.TWO)
    session.append(card)
    session.append(NewHand())
    assert session.state()["cards_seen"] == 1
    assert session.state()["player_hands"][0]["cards"] == []
    session.append(CardDealt(Rank.ACE, replaces=card.id))
    assert session.state()["running_count"] == -1
    assert session.state()["player_hands"][0]["cards"] == []
    session.undo()
    assert session.state()["running_count"] == 1
    session.append(RemoveCard(card.id))
    assert session.state()["cards_seen"] == 0
    session.undo()
    session.append(NewShoe())
    assert session.state()["cards_seen"] == 0
    session.undo()
    assert session.state()["cards_seen"] == 1
    session.close()


def test_persistence_and_deck_change_undo(tmp_path: Path) -> None:
    path = tmp_path / "session.sqlite3"
    session = Session(path)
    session.append(CardDealt(Rank.FIVE))
    session.configure(RuleConfig(decks=4), RoundingMode.FLOOR)
    assert session.state()["cards_seen"] == 0
    session.close()
    session = Session(path)
    assert session.state()["config"]["decks"] == 4
    assert session.state()["config"]["rounding"] == "floor"
    session.undo()
    assert session.state()["config"]["decks"] == 6
    assert session.state()["cards_seen"] == 1
    session.close()


def test_multiple_hands_sources_and_atomic_invalid_event() -> None:
    session = Session(":memory:")
    for event in [CardDealt(Rank.EIGHT), CardDealt(Rank.ACE, hand_id="2", from_split=True),
                  CardDealt(Rank.KING, hand_id="2", from_split=True),
                  CardDealt(Rank.SIX, Source.DEALER_UP), CardDealt(Rank.THREE, Source.OTHER, "neighbor")]:
        session.append(event)
    state = session.state()
    assert len(state["player_hands"]) == 2
    assert not state["player_hands"][1]["blackjack"]
    assert state["cards_seen"] == 5
    with pytest.raises(ValueError, match="one dealer"):
        session.append(CardDealt(Rank.TWO, Source.DEALER_UP))
    assert session.state() == state
    session.close()


@given(st.lists(st.sampled_from(list(Rank)), max_size=16))
def test_undo_replay_property(ranks: list[Rank]) -> None:
    session = Session(":memory:")
    states = []
    for rank in ranks:
        states.append(session.state())
        session.append(CardDealt(rank))
    for expected in reversed(states):
        session.undo()
        actual = session.state()
        actual.pop("revision")
        expected.pop("revision")
        assert actual == expected
    session.close()


def test_invalid_removal_and_impossible_shoe() -> None:
    with pytest.raises(ValueError):
        replay([RemoveCard("missing")])
    with pytest.raises(ValueError):
        replay([CardDealt(Rank.ACE) for _ in range(25)])
    card = CardDealt(Rank.TWO)
    with pytest.raises(ValueError, match="unique"):
        replay([card, replace(card, rank=Rank.THREE)])
