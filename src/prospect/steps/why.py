"""Why this person, rewritten after step 2 from verified facts only, so the rep never reads stale search notes."""

from pydantic import BaseModel

from prospect.llm import Runner
from prospect.models import CompanyProfile, Contact
from prospect.seller import Seller


class WhyAnswer(BaseModel):
    why: str


PROMPT = """A sales rep selling {seller} ({summary}) will contact {name}, {title} at {company}, as the {role}.
Confirmed current role: {evidence}
What we know about the company now:
{signals}

Write ONE sentence, at most 30 words, on why this person matters in this deal. Use only the facts above. No notes
about sources, checks, hints, confidence or what still needs confirming."""


def write_why(contact: Contact, profile: CompanyProfile, seller: Seller, run: Runner) -> str:
    prompt = PROMPT.format(
        seller=seller.name, summary=seller.summary.strip(), name=contact.name, title=contact.title,
        company=profile.resolved_name, role=seller.roles[contact.buying_role].label, evidence=contact.role_evidence,
        signals="\n".join(f"- {s.text}" for s in profile.signals) or "- (no recent signals found)",
    )  # fmt: skip
    return run(prompt, WhyAnswer, step="why").data.why
