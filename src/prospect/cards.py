"""Memory layer: one card per contact, kept between runs. Fresh cards skip re-verification and re-research."""

from datetime import date, timedelta
from pathlib import Path

from pydantic import BaseModel

from pydantic import Field

from prospect.models import Candidate, Contact, ContactContext
from prospect.steps.drafts import short_name
from prospect.steps.verify import person_key, slug


class Card(BaseModel):
    updated_at: date
    contact: Contact
    context: ContactContext | None = None


class Pool(BaseModel):
    """Everyone ever found at a company, who holds each role, and who was ruled out (left the company)."""

    candidates: list[Candidate] = Field(default_factory=list)
    picked: dict[str, str] = Field(default_factory=dict, description="buying role -> person_key")
    dropped: dict[str, str] = Field(default_factory=dict, description="person_key -> reason")


class CardStore:
    def __init__(self, root: Path, ttl_days: int, today: date):
        self.root, self.ttl, self.today = root, timedelta(days=ttl_days), today

    def path(self, company: str, name: str) -> Path:
        return self.root / slug(short_name(company)) / f"{person_key(name)}.json"

    def get(self, company: str, name: str) -> Card | None:
        p = self.path(company, name)
        if not p.exists():
            return None
        card = Card.model_validate_json(p.read_text())
        return card if self.today - card.updated_at <= self.ttl else None

    def put(self, company: str, contact: Contact, context: ContactContext | None = None) -> Path:
        p = self.path(company, contact.name)
        p.parent.mkdir(parents=True, exist_ok=True)
        card = Card(updated_at=self.today, contact=contact, context=context)
        p.write_text(card.model_dump_json(indent=2))
        return p

    def load_pool(self, company: str) -> Pool:
        p = self.root / slug(short_name(company)) / "_pool.json"
        return Pool.model_validate_json(p.read_text()) if p.exists() else Pool()

    def save_pool(self, company: str, pool: Pool) -> None:
        p = self.root / slug(short_name(company)) / "_pool.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(pool.model_dump_json(indent=2))
