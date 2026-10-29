"""Typed records shared by every module. Place.from_qloo is the only code that knows Qloo's JSON layout."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Category = Literal["restaurant", "cafe", "bar", "bakery", "fast_food", "non_food"]
FOOD_CATEGORIES = {"restaurant", "cafe", "bar", "bakery", "fast_food"}
TierSource = Literal["qloo", "inferred_from_user_spend", "inferred_fixed_bands"]


class Transaction(BaseModel):
    date: date
    merchant: str
    amount_usd: float
    city: str


class CleanMerchant(BaseModel):
    raw: str
    name: str = Field(min_length=1)
    category: Category
    city: str = Field(min_length=1)
    cleaned_by: Literal["llm", "rules"] = "llm"


class Tag(BaseModel):
    id: str
    name: str = ""
    type: str = ""


class Place(BaseModel):
    entity_id: str
    name: str
    address: str = ""
    price_level: int | None = None
    business_rating: float | None = None
    tags: list[Tag] = []

    @classmethod
    def from_qloo(cls, raw: dict) -> "Place":
        props = raw.get("properties") or {}
        return cls(**cls._fields_from(raw, props))

    @staticmethod
    def _fields_from(raw: dict, props: dict) -> dict:
        return {
            "entity_id": raw["entity_id"],
            "name": raw.get("name", ""),
            "address": props.get("address") or "",
            "price_level": props.get("price_level"),
            "business_rating": props.get("business_rating"),
            # /search and /entities name the key "tag_id"; /v2/insights names it "id".
            "tags": [
                Tag(id=t.get("id") or t["tag_id"], name=t.get("name", ""), type=t.get("type", ""))
                for t in raw.get("tags", [])
                if isinstance(t, dict) and (t.get("id") or t.get("tag_id"))
            ],
        }

    def tag_ids(self) -> set[str]:
        return {t.id for t in self.tags}


class Twin(Place):
    affinity: float
    explain: dict[str, float] = {}  # input entity_id -> explainability score (0-1)

    @classmethod
    def from_qloo(cls, raw: dict) -> "Twin":
        query = raw.get("query") or {}
        rows = (query.get("explainability") or {}).get("signal.interests.entities", [])
        return cls(
            **cls._fields_from(raw, raw.get("properties") or {}),
            affinity=query.get("affinity", 0.0),
            explain={r["entity_id"]: r.get("score", 0.0) for r in rows if "entity_id" in r},
        )


class RankedTwin(Twin):
    score: float
    jaccard: float = 0.0
    shared: list[str] = []  # meaningful cuisine/genre concepts shared with the origin
    tiers_down: int = 1


class Resolution(BaseModel):
    merchant: CleanMerchant
    status: Literal["resolved", "needs_review"]
    reason: str = ""
    place: Place | None = None
    match_score: float = 0.0
    branch_note: str = ""


class TierInfo(BaseModel):
    tier: int = Field(ge=1, le=4)
    source: TierSource


class Saving(BaseModel):
    monthly_usd_full: float  # every visit swapped; kept in report.json, not headlined
    monthly_usd_half: float  # 1 in 2 visits swapped; the headline number
    origin_avg: float  # the user's own average bill at this merchant
    target_avg: float  # the user's average bill at the twin's tier (or fallback)
    visits_per_month: float
    estimate: bool
    note: str = ""


class TraceEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    step: str
    tool: str
    target: str = ""
    status: str
    ms: int = 0
    detail: str = ""
