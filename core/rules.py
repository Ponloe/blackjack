"""Rules supported by the shoe-game strategy tables and simulator."""

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class RuleConfig:
    decks: int = 6
    dealer_hits_soft_17: bool = False
    double_after_split: bool = True
    surrender: bool = False
    penetration: float = 0.75

    def __post_init__(self) -> None:
        if type(self.decks) is not int or not 4 <= self.decks <= 8:
            raise ValueError("Strategy tables currently support 4–8 decks")
        for name in ("dealer_hits_soft_17", "double_after_split", "surrender"):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"{name} must be a boolean")
        if isinstance(self.penetration, bool) or not isinstance(self.penetration, (int, float)):
            raise ValueError("penetration must be a number")
        if not math.isfinite(self.penetration) or not 0 < self.penetration <= 0.90:
            raise ValueError("penetration must be greater than 0 and at most 0.90")

    @property
    def strategy_key(self) -> str:
        soft = "H17" if self.dealer_hits_soft_17 else "S17"
        double = "DAS" if self.double_after_split else "NDAS"
        surrender = "LS" if self.surrender else "NS"
        return f"4-8/{soft}/{double}/{surrender}"
