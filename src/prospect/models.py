"""Data passed between pipeline steps. Every fact carries the public source it came from."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

BuyingRole = Literal["economic_buyer", "decision_maker", "champion"]
Seniority = Literal["c_level", "vp", "director", "head", "manager", "other"]
ROLE_ORDER: tuple[BuyingRole, ...] = ("economic_buyer", "decision_maker", "champion")


class Source(BaseModel):
    url: str
    title: str = ""
    published: str | None = Field(None, description="YYYY-MM-DD or YYYY-MM if the page shows a date, else null")
    opened: bool = Field(
        False, description="True only if you opened this page yourself and read the fact on it; "
        "false if you only saw it in search results"
    )


def published_date(s: Source) -> date | None:
    """Read YYYY-MM-DD, YYYY-MM or YYYY; a partial date counts as its first day."""
    parts = (s.published or "").strip()[:10].split("-")
    try:
        return date(int(parts[0]), int(parts[1]) if len(parts) > 1 else 1, int(parts[2]) if len(parts) > 2 else 1)
    except (ValueError, IndexError):
        return None


class Fact(BaseModel):
    text: str
    source: Source


class CompanyProfile(BaseModel):
    input_name: str
    resolved_name: str
    domain: str | None
    fit: Literal["strong", "partial", "weak"]
    fit_reason: str
    fit_sources: list[Source] = Field(default_factory=list)
    signals: list[Fact] = Field(default_factory=list)


class Candidate(BaseModel):
    name: str
    title: str
    company: str
    buying_role: BuyingRole
    seniority: Seniority = Field("other", description="c_level, vp, director, head, manager or other, from the title")
    relevance: int = Field(ge=1, le=5, description="How much this person owns what the seller sells, 1-5")
    relevance_reason: str
    why: str
    linkedin_url: str | None = None
    sources: list[Source] = Field(default_factory=list)


class Contact(Candidate):
    confidence: Literal["high", "medium", "low"]
    linkedin_status: Literal["matched", "not_found"]
    role_evidence: str


class Alternate(BaseModel):
    """A runner-up for a role, not verified, shown so the rep can choose differently."""

    name: str
    title: str
    relevance: int
    why_not: str
    source_url: str


class ContactContext(BaseModel):
    summary: list[Fact] = Field(description="2-4 sentences: recent activity, role change, company news; each sourced")
    pain: Fact | None = Field(None, description="The role's pain as it shows in this company's facts")
    personalization: Literal["personal", "company", "role"]
    shared_connections: str = "not available without LinkedIn login"


class Drafts(BaseModel):
    linkedin_note: str
    email_subject: str
    email_body: str
    hooks: list[str] = Field(default_factory=list, description="Exact texts of the prospect facts the drafts rely on")
    seller_facts: list[str] = Field(default_factory=list, description="Exact texts of the seller facts used")


class CheckResult(BaseModel):
    """Every contact ends with drafts that passed the checks; this says how they got there."""

    mode: Literal["personal", "safe", "template"] = Field(
        description="personal = built on facts about the person or company; safe = written only from seller facts; "
        "template = seller.yaml fallback"
    )
    basis: Literal["personal", "company", "role"] = Field(description="What the final drafts' personalization rests on")
    attempts: int
    fixed: list[str] = Field(default_factory=list, description="Problems found in earlier attempts and fixed")
    judge_reason: str = ""


class ContactResult(BaseModel):
    """One person, enriched step by step: each step adds its part, none replaces another's."""

    contact: Contact
    context: ContactContext | None = None
    drafts: Drafts | None = None
    check: CheckResult | None = None


class CompanyResult(BaseModel):
    input_name: str
    status: Literal["done", "needs_decision", "failed", "not_found"]
    reason: str | None = None
    profile: CompanyProfile | None = None
    unconfirmed: list[Contact] = Field(default_factory=list, description="Found, but only old sources: rep to check")
    role_notes: dict[BuyingRole, str] = Field(default_factory=dict, description="Why a buying role has no contact")
    alternates: dict[BuyingRole, list[Alternate]] = Field(default_factory=dict)
    contacts: list[ContactResult] = Field(default_factory=list)


class RunSummary(BaseModel):
    companies: int
    processed: int
    needs_decision: int
    failed: int
    not_found: int
    contacts: int
    contacts_high: int
    drafts_by_basis: dict[str, int] = Field(description="personal / company / role")
    passed_first_try: int
    duration_s: float
    cost_usd: float = Field(description="Model cost at list price; included in a Claude subscription")
    searches: int


class RunOutput(BaseModel):
    """results.json: everything the run produced, ready for a CRM import."""

    started_at: str
    seller: str
    summary: RunSummary
    companies: list[CompanyResult]
