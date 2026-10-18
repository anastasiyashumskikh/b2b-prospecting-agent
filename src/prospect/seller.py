"""The seller the agent prospects for. The agent may claim only what seller.yaml states."""

from pathlib import Path

import yaml
from pydantic import BaseModel

from prospect.models import BuyingRole, Fact


class RoleSpec(BaseModel):
    label: str = ""
    titles: list[str]
    pain: str
    hints: list[str] = []


class Fallback(BaseModel):
    linkedin_note: str
    email_subject: str
    email_body: str


class Seller(BaseModel):
    name: str
    company: str
    summary: str
    icp: str
    facts: list[Fact]
    offers: list[str]
    fallback: Fallback
    roles: dict[BuyingRole, RoleSpec]


def load_seller(path: Path) -> Seller:
    return Seller.model_validate(yaml.safe_load(path.read_text()))
