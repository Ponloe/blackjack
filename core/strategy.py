"""Validated JSON lookup engine; only action eligibility lives in Python."""

import json
from copy import deepcopy
from enum import StrEnum
from pathlib import Path
from typing import Any

from core.cards import Rank
from core.hand import Hand
from core.rules import RuleConfig

DEFAULT_TABLE_PATH = Path(__file__).resolve().parent.parent / "data" / "basic_strategy.json"
Tables = dict[str, dict[str, list[str | None]]]


class Action(StrEnum):
    HIT = "HIT"
    STAND = "STAND"
    DOUBLE = "DOUBLE"
    SPLIT = "SPLIT"
    SURRENDER = "SURRENDER"


class Strategy:
    def __init__(self, rules: RuleConfig = RuleConfig(), path: Path = DEFAULT_TABLE_PATH) -> None:
        self.rules = rules
        with path.open(encoding="utf-8") as stream:
            data = json.load(stream)
        if data.get("schema_version") != 1:
            raise ValueError("Unsupported strategy schema version")
        self.columns: list[str] = data["dealer_columns"]
        if self.columns != ["2", "3", "4", "5", "6", "7", "8", "9", "10", "A"]:
            raise ValueError("Invalid dealer columns")
        self.codes = {code: tuple(Action(action) for action in actions) for code, actions in data["codes"].items()}
        self.tables = self._resolve(data["rule_sets"], rules.strategy_key, ())
        self._validate()

    def _resolve(self, sets: dict[str, Any], key: str, ancestors: tuple[str, ...]) -> Tables:
        if key in ancestors:
            raise ValueError("Strategy inheritance cycle")
        if key not in sets:
            raise ValueError(f"Missing strategy rule set: {key}")
        definition = sets[key]
        if "extends" in definition:
            tables = self._resolve(sets, definition["extends"], ancestors + (key,))
        else:
            tables = deepcopy(definition["tables"])
        for category, rows in definition.get("overrides", {}).items():
            for row, cells in rows.items():
                for column, code in cells.items():
                    tables[category][row][self.columns.index(column)] = code
        return tables

    def _validate(self) -> None:
        required = {
            "hard": {str(total) for total in range(4, 22)},
            "soft": {str(total) for total in range(12, 22)},
            "pairs": {"A", *(str(value) for value in range(2, 11))},
        }
        if self.tables.keys() != required.keys():
            raise ValueError("Invalid strategy categories")
        for category, rows in required.items():
            if self.tables[category].keys() != rows:
                raise ValueError(f"Incomplete {category} table")
            for cells in self.tables[category].values():
                if len(cells) != len(self.columns):
                    raise ValueError("Every strategy row must have ten cells")
                for code in cells:
                    if code is None and category == "pairs":
                        continue
                    if code not in self.codes or not self.codes[code]:
                        raise ValueError(f"Invalid strategy code: {code}")
                    actions = self.codes[code]
                    terminal = (Action.SPLIT,) if category == "pairs" else (Action.HIT, Action.STAND)
                    if actions[-1] not in terminal:
                        raise ValueError(f"Missing legal fallback for {category}: {code}")

    def recommend(
        self,
        hand: Hand,
        dealer_up: Rank,
        *,
        can_double: bool = True,
        can_split: bool = True,
        can_surrender: bool = True,
    ) -> Action | None:
        """None means incomplete or finished. Caller must resolve dealer peek first.

        Split-ace draw limits and already-stood/doubled hands are caller state.
        Eligibility flags may restrict actions but cannot override game rules.
        """
        if len(hand.cards) < 2 or hand.total >= 21:
            return None
        first_two = len(hand.cards) == 2
        allowed = {
            Action.HIT: True,
            Action.STAND: True,
            Action.DOUBLE: can_double and first_two and (not hand.from_split or self.rules.double_after_split),
            Action.SPLIT: can_split and hand.is_pair,
            Action.SURRENDER: can_surrender and first_two and not hand.from_split and self.rules.surrender,
        }
        column = 9 if dealer_up is Rank.ACE else dealer_up.hard_value - 2
        if hand.is_pair:
            rank = "A" if hand.cards[0] is Rank.ACE else str(hand.cards[0].hard_value)
            code = self.tables["pairs"][rank][column]
            if code is not None:
                for action in self.codes[code]:
                    if allowed[action]:
                        return action
        category = "soft" if hand.is_soft else "hard"
        code = self.tables[category][str(hand.total)][column]
        assert code is not None
        for action in self.codes[code]:
            if allowed[action]:
                return action
        raise ValueError("Strategy cell has no legal fallback")
