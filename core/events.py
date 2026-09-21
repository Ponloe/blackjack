"""Replayable session events. No database, HTTP, or camera dependencies."""

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any, Iterable
from uuid import uuid4

from core.cards import Rank
from core.hand import Hand
from core.rules import RuleConfig
from core.shoe import Shoe


class Source(StrEnum):
    PLAYER = "player"
    DEALER_UP = "dealer_up"
    DEALER_HOLE = "dealer_hole"
    OTHER = "other"


def new_id() -> str:
    return uuid4().hex


@dataclass(frozen=True)
class CardDealt:
    rank: Rank
    source: Source = Source.PLAYER
    hand_id: str = "1"
    from_split: bool = False
    replaces: str | None = None
    id: str = field(default_factory=new_id)


@dataclass(frozen=True)
class NewHand:
    id: str = field(default_factory=new_id)


@dataclass(frozen=True)
class NewShoe:
    decks: int | None = None
    id: str = field(default_factory=new_id)


@dataclass(frozen=True)
class RemoveCard:
    card_id: str
    id: str = field(default_factory=new_id)


Event = CardDealt | NewHand | NewShoe | RemoveCard


@dataclass(frozen=True)
class SeenCard:
    id: str
    rank: Rank
    source: Source
    hand_id: str
    from_split: bool
    hand_number: int


@dataclass(frozen=True)
class ReplayState:
    cards: tuple[SeenCard, ...]
    hand_number: int
    shoe_number: int
    shoe: Shoe

    @property
    def current_cards(self) -> tuple[SeenCard, ...]:
        return tuple(card for card in self.cards if card.hand_number == self.hand_number)

    def hand(self, hand_id: str = "1", source: Source = Source.PLAYER) -> Hand:
        cards = tuple(card for card in self.current_cards if card.source == source and card.hand_id == hand_id)
        return Hand(tuple(card.rank for card in cards), any(card.from_split for card in cards))


def replay(events: Iterable[Event], rules: RuleConfig = RuleConfig()) -> ReplayState:
    cards: list[SeenCard] = []
    hand_number, shoe_number = 1, 1
    decks = rules.decks
    ids: set[str] = set()
    for event in events:
        if not event.id or event.id in ids:
            raise ValueError("Event IDs must be unique")
        ids.add(event.id)
        if isinstance(event, NewShoe):
            cards.clear()
            hand_number = 1
            shoe_number += 1
            if event.decks is not None:
                decks = RuleConfig(decks=event.decks).decks
        elif isinstance(event, NewHand):
            hand_number += 1
        elif isinstance(event, RemoveCard):
            index = next((i for i, card in enumerate(cards) if card.id == event.card_id), None)
            if index is None:
                raise ValueError("That card is no longer in this shoe")
            cards.pop(index)
        elif isinstance(event, CardDealt):
            if not isinstance(event.rank, Rank) or not isinstance(event.source, Source):
                raise ValueError("Invalid rank or source")
            if not event.hand_id or len(event.hand_id) > 32:
                raise ValueError("Invalid hand ID")
            position = None
            card_hand = hand_number
            if event.replaces:
                position = next((i for i, card in enumerate(cards) if card.id == event.replaces), None)
                if position is None:
                    raise ValueError("The card to correct is no longer in this shoe")
                card_hand = cards[position].hand_number
            card = SeenCard(event.id, event.rank, event.source, event.hand_id, event.from_split, card_hand)
            if position is None:
                cards.append(card)
            else:
                cards[position] = card
        else:
            raise ValueError("Unknown event type")
    current = [card for card in cards if card.hand_number == hand_number]
    if sum(card.source == Source.DEALER_UP for card in current) > 1:
        raise ValueError("Only one dealer up-card is allowed; correct or remove the existing card")
    if len({card.hand_id for card in current if card.source == Source.PLAYER}) > 4:
        raise ValueError("At most four player hands are supported")
    shoe = Shoe(decks, (card.rank for card in cards))
    return ReplayState(tuple(cards), hand_number, shoe_number, shoe)


def event_to_dict(event: Event) -> dict[str, Any]:
    return {"type": type(event).__name__, **asdict(event)}


def event_from_dict(data: dict[str, Any]) -> Event:
    fields = dict(data)
    kind = fields.pop("type")
    if kind == "CardDealt":
        fields["rank"] = Rank(fields["rank"])
        fields["source"] = Source(fields["source"])
        return CardDealt(**fields)
    if kind == "NewHand":
        return NewHand(**fields)
    if kind == "NewShoe":
        return NewShoe(**fields)
    if kind == "RemoveCard":
        return RemoveCard(**fields)
    raise ValueError(f"Unknown event type: {kind}")
