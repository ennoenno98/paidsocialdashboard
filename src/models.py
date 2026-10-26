"""Pydantic schemas shared across ingest, transform and app layers."""

from __future__ import annotations

import datetime as _dt
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Brand = Literal["vegavero", "wowtamins", "jasnum", "vanatari"]
Platform = Literal["instagram", "tiktok"]
Market = Literal["IT", "DE", "INT"]
Kind = Literal["organic", "boosting"]
PeriodType = Literal["cw", "month"]
ErBasis = Literal["reach", "views"]
ReachSource = Literal["klar", "manual", "n/a"]


class AccountKey(BaseModel):
    """Canonical account identity: brand/platform/market (+ organic vs boosting block)."""

    model_config = ConfigDict(frozen=True)

    brand: Brand
    platform: Platform
    market: Market
    kind: Kind = "organic"
    note: str | None = None

    @property
    def key(self) -> str:
        return f"{self.brand}/{self.platform}/{self.market}"

    @property
    def label(self) -> str:
        return f"{self.brand.capitalize()} {self.platform.capitalize()} {self.market}"


class BlockReport(BaseModel):
    """One entry of the block-coverage report produced by the workbook parser."""

    sheet: str
    title: str
    row_start: int
    row_end: int
    account: str | None = None
    kind: Kind | None = None
    period_type: PeriodType | None = None
    year: int | None = None
    n_periods: int = 0
    n_metrics: int = 0
    n_values: int = 0
    status: Literal["ok", "no_data", "unmapped_title", "unparsed"] = "ok"
    warnings: list[str] = Field(default_factory=list)


class Issue(BaseModel):
    """Data-quality issue surfaced on the Data quality page."""

    source: str
    severity: Literal["info", "warn", "error"] = "warn"
    where: str
    message: str


class Creator(BaseModel):
    """Influencer master record from the Creators sheet. The address column is never read."""

    name: str | None = None
    country: str | None = None
    followers: float | None = None
    field: str | None = None
    account_url: str | None = None
    handle: str | None = None
    platform: Platform | None = None
    deal: str | None = None
    code: str | None = None


class KlarInfluencerRow(BaseModel):
    """One row of Klar's influencer_flex report (dimensions + metrics we use).

    Dimension/metric names mirror Klar's report schema verbatim.
    """

    model_config = ConfigDict(extra="allow")

    influencer_name: str | None = None
    campaign_name: str | None = None
    platform: str | None = None
    type_of_partnership: str | None = None
    category: str | None = None
    post_type: str | None = None
    posting_date: _dt.date | None = None
    date: _dt.date | None = None
    discount_code: str | None = None
    utm_source: str | None = None
    utm_medium: str | None = None
    utm_campaign: str | None = None
    utm_term: str | None = None
    utm_content: str | None = None
    advertised_sku: str | None = None

    costs: float = 0.0
    fixed_costs: float = 0.0
    var_costs: float = 0.0
    orders: float = 0.0
    net_revenue: float = 0.0
    gross_revenue: float = 0.0
    new_customers: float = 0.0
    roas: float | None = None
    gross_roas: float | None = None
    cac: float | None = None
    cpo: float | None = None
    sessions: float = 0.0
    conversion_rate: float | None = None
    cpm: float | None = None
    cost_per_follower: float | None = None
    reach_share: float | None = None
    reach: float | None = None
    followers: float | None = None


class IgMedia(BaseModel):
    """One Instagram media item for an own account, with insights."""

    account: str  # canonical key brand/platform/market
    ig_user_id: str
    media_id: str
    timestamp: _dt.datetime
    media_type: str | None = None
    media_product_type: str | None = None
    permalink: str | None = None
    caption: str | None = None
    like_count: float | None = None
    comments_count: float | None = None
    reach: float | None = None
    saved: float | None = None
    shares: float | None = None
    total_interactions: float | None = None
    views: float | None = None
    fetched_at: _dt.datetime


class BusinessDiscovery(BaseModel):
    """Public data for a third-party creator via Business Discovery. No reach available here."""

    handle: str
    scannable: bool
    error: str | None = None
    followers_count: float | None = None
    media_count: float | None = None
    media: list[dict] = Field(default_factory=list)  # like_count, comments_count, timestamp, media_type
    fetched_at: _dt.datetime


class ManualReach(BaseModel):
    """Row of data/manual/influencer_reach.csv (creator-provided insights)."""

    handle: str
    post_url: str | None = None
    date: _dt.date | None = None
    reach: float
    source: str = "creator_insights"
