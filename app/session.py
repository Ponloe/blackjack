"""Atomic SQLite event-log persistence and derived dashboard state."""

import json
import sqlite3
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

from core.counting import RoundingMode, running_count, true_count
from core.events import Event, NewShoe, Source, event_from_dict, event_to_dict, replay
from core.hand import Hand
from core.rules import RuleConfig
from core.strategy import Strategy


class Session:
    """One local session. The app serializes mutations with an asyncio lock."""

    def __init__(self, path: str | Path) -> None:
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(str(path), check_same_thread=False)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS session (id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL)"
        )
        row = self.connection.execute("SELECT payload FROM session WHERE id=1").fetchone()
        payload = json.loads(row[0]) if row else {}
        self.rules = RuleConfig(**payload.get("rules", {}))
        self.initial_decks: int = payload.get("initial_decks", self.rules.decks)
        self.rounding = RoundingMode(payload.get("rounding", "none"))
        self.events = [event_from_dict(event) for event in payload.get("events", [])]
        self.revision: int = payload.get("revision", 0)
        replay(self.events, replace(self.rules, decks=self.initial_decks))

    def close(self) -> None:
        self.connection.close()

    def _save(self, events: list[Event], rules: RuleConfig, rounding: RoundingMode) -> None:
        derived = replay(events, replace(rules, decks=self.initial_decks))
        rules = replace(rules, decks=derived.shoe.decks)
        revision = self.revision + 1
        payload = json.dumps({
            "events": [event_to_dict(event) for event in events],
            "rules": asdict(rules), "rounding": rounding, "revision": revision,
            "initial_decks": self.initial_decks,
        })
        with self.connection:
            self.connection.execute(
                "INSERT INTO session (id, payload) VALUES (1, ?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload",
                (payload,),
            )
        self.events, self.rules, self.rounding, self.revision = events, rules, rounding, revision

    def append(self, event: Event) -> None:
        self._save([*self.events, event], self.rules, self.rounding)

    def undo(self) -> None:
        if not self.events:
            raise ValueError("There is nothing to undo")
        self._save(self.events[:-1], self.rules, self.rounding)

    def configure(self, rules: RuleConfig, rounding: RoundingMode) -> None:
        events = self.events
        if rules.decks != self.rules.decks:
            events = [*events, NewShoe(decks=rules.decks)]
        self._save(events, rules, rounding)

    def state(self) -> dict[str, Any]:
        derived = replay(self.events, replace(self.rules, decks=self.initial_decks))
        count = running_count(card.rank for card in derived.cards)
        current = derived.current_cards
        up_card = next((card.rank for card in current if card.source == Source.DEALER_UP), None)
        dealer_cards = tuple(card.rank for card in current if card.source in (Source.DEALER_UP, Source.DEALER_HOLE))
        dealer = Hand(dealer_cards)
        strategy = Strategy(self.rules)
        hand_ids = sorted({"1", *(card.hand_id for card in current if card.source == Source.PLAYER)})
        hands: list[dict[str, Any]] = []
        for hand_id in hand_ids:
            hand = derived.hand(hand_id)
            action = None
            if up_card is not None and not dealer.is_blackjack:
                split_aces = hand.from_split and bool(hand.cards) and hand.cards[0].value == "A"
                if not split_aces:
                    action = strategy.recommend(hand, up_card, can_split=len(hand_ids) < 4)
            hands.append({
                "id": hand_id, "cards": [card.value for card in hand.cards],
                "total": hand.total, "soft": hand.is_soft, "blackjack": hand.is_blackjack,
                "bust": hand.is_bust, "from_split": hand.from_split, "action": action,
            })
        penetration = derived.shoe.cards_seen / (self.rules.decks * 52)
        return {
            "revision": self.revision,
            "config": {**asdict(self.rules), "rounding": self.rounding},
            "running_count": count,
            "true_count": true_count(count, derived.shoe.decks_remaining, self.rounding),
            "cards_seen": derived.shoe.cards_seen, "cards_remaining": derived.shoe.cards_remaining,
            "decks_remaining": derived.shoe.decks_remaining,
            "penetration": penetration, "shuffle_due": penetration >= self.rules.penetration,
            "hand_number": derived.hand_number, "shoe_number": derived.shoe_number,
            "player_hands": hands, "dealer_up": up_card,
            "dealer_cards": [rank.value for rank in dealer_cards], "dealer_blackjack": dealer.is_blackjack,
            "recent_cards": [asdict(card) for card in reversed(derived.cards[-30:])],
            "event_count": len(self.events), "can_undo": bool(self.events),
        }
