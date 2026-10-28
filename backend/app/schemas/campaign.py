import uuid
from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator


class AudienceFilters(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    query: str = Field(default="", max_length=150)
    company_id: uuid.UUID | None = None
    lead_stage: Literal["new", "contacted", "qualified", "proposal", "won", "lost"] | None = None
    owner_id: uuid.UUID | None = None
    engagement: Literal["delivered", "reply", "email.opened", "email.clicked"] | None = None
    contact_ids: list[uuid.UUID] = Field(default_factory=list, max_length=1000)


class CampaignInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=3000)
    channel: Literal["email", "sms"]
    provider: Literal["auto", "gmail", "resend", "twilio"] = "auto"
    agent_id: uuid.UUID | None = None
    template_id: uuid.UUID | None = None
    subject: str = Field(default="", max_length=200)
    body: str = Field(min_length=1, max_length=10000)
    audience: AudienceFilters = Field(default_factory=AudienceFilters)
    timezone: str = "UTC"
    scheduled_at: AwareDatetime | None = None
    window_start: int = Field(default=0, ge=0, le=23)
    window_end: int = Field(default=24, ge=1, le=24)

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("Use an IANA timezone such as Asia/Karachi") from exc
        return value

    @model_validator(mode="after")
    def validate_channel(self):
        if self.window_start >= self.window_end:
            raise ValueError("Sending window end must be after start")
        if self.channel == "email" and (not self.subject or self.provider == "twilio"):
            raise ValueError("Email requires a subject and an email provider")
        if self.channel == "sms" and (len(self.body) > 1560 or self.provider in {"gmail", "resend"}):
            raise ValueError("SMS requires Twilio and at most 1560 characters")
        if "\r" in self.subject or "\n" in self.subject:
            raise ValueError("Subject must be one line")
        return self


class AudienceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    channel: Literal["email", "sms"]
    filters: AudienceFilters = Field(default_factory=AudienceFilters)


class SegmentInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=120)
    filters: AudienceFilters


class ConsentInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    contact_id: uuid.UUID
    channel: Literal["email", "sms"]
    granted: bool
    evidence: str = Field(min_length=5, max_length=2000)


class GenerateInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    objective: str = Field(min_length=5, max_length=3000)
    channel: Literal["email", "sms"]
    agent_id: uuid.UUID | None = None
    kind: Literal["campaign", "subject", "body", "introduction", "follow_up", "alternative"] = "campaign"
