"""B4 extraction schema (verbatim): the frozen record the model must return."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class NullReason(str, Enum):
    """Why a field was left null."""

    not_stated = 'not_stated'
    ambiguous = 'ambiguous'


class NumField(BaseModel):
    """A number the document states explicitly."""

    value: float | None = None
    null_reason: NullReason | None = None
    evidence_quote: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class TextField(BaseModel):
    """A short text fact the document states explicitly."""

    value: str | None = None
    null_reason: NullReason | None = None
    evidence_quote: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class ThemeMention(BaseModel):
    """Whether a configured theme is discussed, and in which direction."""

    mentioned: bool = False
    direction: str | None = None
    evidence_quote: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class ExtractionRecord(BaseModel):
    """One document's extracted facts. The model never computes derived values."""

    schema_version: str
    document_id: str
    fiscal_year: int | None = None
    fiscal_quarter: int | None = None
    currency: str | None = None
    units: str | None = None
    reported_eps: NumField = NumField()
    prior_year_eps: NumField = NumField()
    consensus_eps: NumField = NumField()
    eps_basis: TextField = TextField()
    revenue: NumField = NumField()
    revenue_yoy_growth: NumField = NumField()
    guidance_direction: TextField = TextField()
    guidance_metric: TextField = TextField()
    tone: TextField = TextField()
    theme_mentions: dict[str, ThemeMention] = {}
