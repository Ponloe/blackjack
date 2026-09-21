"""Small JSON API used by the single-page dashboard."""

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from core.cards import Rank
from core.counting import RoundingMode
from core.events import CardDealt, NewHand, NewShoe, RemoveCard, Source
from core.rules import RuleConfig

router = APIRouter(prefix="/api")


class CardInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rank: Rank
    source: Source = Source.PLAYER
    hand_id: str = Field(default="1", pattern=r"^[a-zA-Z0-9_-]{1,32}$")
    from_split: bool = Field(default=False, strict=True)
    replaces: str | None = Field(default=None, max_length=64)


class RemoveInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    card_id: str = Field(min_length=1, max_length=64)


class ConfigInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decks: int | None = Field(default=None, ge=4, le=8, strict=True)
    dealer_hits_soft_17: bool | None = Field(default=None, strict=True)
    double_after_split: bool | None = Field(default=None, strict=True)
    surrender: bool | None = Field(default=None, strict=True)
    penetration: float | None = Field(default=None, gt=0, le=0.90)
    rounding: RoundingMode | None = None


@router.get("/session/state")
async def get_state(request: Request) -> dict[str, Any]:
    return request.app.state.service.snapshot()


@router.post("/card")
async def card(body: CardInput, request: Request) -> dict[str, Any]:
    service = request.app.state.service
    return await service.mutate(lambda: service.session.append(CardDealt(**body.model_dump())))


@router.post("/remove-card")
async def remove_card(body: RemoveInput, request: Request) -> dict[str, Any]:
    service = request.app.state.service
    return await service.mutate(lambda: service.session.append(RemoveCard(body.card_id)))


@router.post("/undo")
async def undo(request: Request) -> dict[str, Any]:
    service = request.app.state.service
    return await service.mutate(service.session.undo)


@router.post("/new-hand")
async def new_hand(request: Request) -> dict[str, Any]:
    service = request.app.state.service
    return await service.mutate(lambda: service.session.append(NewHand()))


@router.post("/new-shoe")
async def new_shoe(request: Request) -> dict[str, Any]:
    service = request.app.state.service
    return await service.mutate(lambda: service.session.append(NewShoe()))


@router.put("/config")
async def config(body: ConfigInput, request: Request) -> dict[str, Any]:
    service = request.app.state.service

    def apply() -> None:
        updates = body.model_dump(exclude_none=True)
        rounding = updates.pop("rounding", service.session.rounding)
        existing = service.session.state()["config"]
        existing.pop("rounding")
        service.session.configure(RuleConfig(**{**existing, **updates}), rounding)

    return await service.mutate(apply)
