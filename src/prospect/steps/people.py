"""Step 1. People: find the buying group, pick the best person per role.

The model searches (one call per role, so each role gets the full search budget) and rates each
candidate; the code picks. Order: relevance to what the seller sells, then seniority, then source
count and freshness. Candidates accumulate across runs in a per-company pool, and the person picked
last time keeps the role unless someone clearly better appears, so picks do not jump between runs.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Protocol

from pydantic import BaseModel, Field

from prospect.llm import Runner
from prospect.models import ROLE_ORDER, Alternate, BuyingRole, Candidate, CompanyProfile, published_date
from prospect.seller import RoleSpec, Seller
from prospect.steps.verify import person_key

MIN_RELEVANCE = 3
MAX_ALTERNATES = 2
SENIORITY_RANK = {"c_level": 4, "vp": 3, "director": 2, "head": 2, "manager": 1, "other": 0}


class PeopleSource(Protocol):
    """Where people come from. Web search today; Exa or a licensed people database plug in here."""

    def find(self, profile: CompanyProfile, seller: Seller, known: list[Candidate]) -> list[Candidate]: ...


class PeopleAnswer(BaseModel):
    candidates: list[Candidate] = Field(description="Up to 5 for this buying role; empty if none found")


PROMPT = """A sales rep selling {seller} ({summary}) prepares outreach to {company} ({domain}).
What we know about the company now:
{signals}

Find people at {company} for ONE buying role, up to 5 candidates, best first:
{role}
{known}
How to search:
- Where people show up publicly, roughly in this order:
  - customer-experience conference speaker pages (Customer Contact Week, CX Network, CCW Europe, Gartner
    customer service summits, vendor events of Salesforce, Genesys, NICE, Zendesk);
  - trade media interviews and quotes (CX Today, CX Dive, Customer Experience Magazine, CX Network articles),
    podcasts and webinars about customer service or AI;
  - the company's own newsroom, leadership and team pages, press releases, engineering or careers blogs,
    job postings that name the hiring leader;
  - search results for public LinkedIn profiles and posts (site:linkedin.com/in or /posts "{company}" plus a
    title). Search engines apply site: loosely and may refuse person-profile queries; then rely on the above.
  Take name and title from what the pages and results show; do not open linkedin.com pages.
- People-directory sites (RocketReach, ZoomInfo, TheOfficialBoard, Apollo and similar) may point you to a
  name but never count as a source: confirm the person on another public page or leave them out.
- Titles differ between companies. A close title is fine if the person clearly owns the same area.
- If direct searches give nobody, try once more: other title variants, queries in the language of the
  company's home country, news about appointments. Still nobody: return an empty list.
- Only people who work at {company} now. Each needs at least one source URL where they are named
  together with {company}; give the page date if visible. Never invent a person.
- linkedin_url only if a search result shows the person's own linkedin.com/in/ profile; otherwise null.

For each candidate:
- buying_role: "{role_key}".
- seniority from the title: c_level, vp, director, head, manager or other.
- relevance 1-5: how much this person owns what we sell, i.e. customer support, the contact center, or
  AI in customer experience. 5 = owns it and there is public proof (interview, press release, post about it);
  4 = owns it, no public words about it; 3 = adjacent (all of CX, digital transformation, IT without a clear
  link to support); 1-2 = the title fits but the job is about something else.
  relevance_reason: one line.
- why: one line on why this person matters in this deal, tied to a company fact above when possible."""


def _role_block(role: BuyingRole, spec: RoleSpec) -> str:
    lines = [f"- {role} ({spec.label}). Typical titles: {', '.join(spec.titles)}. Their pain: {spec.pain}"]
    return "\n".join(lines + [f"  Hint: {h}" for h in spec.hints])


class WebSearchPeopleSource:
    def __init__(self, run: Runner):
        self.run = run

    def find(self, profile: CompanyProfile, seller: Seller, known: list[Candidate]) -> list[Candidate]:
        signals = "\n".join(f"- {s.text}" for s in profile.signals) or "- (no recent signals found)"
        found: list[Candidate] = []
        for role, spec in seller.roles.items():
            mine = [c for c in known if c.buying_role == role]
            known_text = (
                "\nAlready known for this role (no need to return them again; look for anyone stronger):\n"
                + "\n".join(f"- {c.name}, {c.title}" for c in mine) + "\n"
            ) if mine else ""  # fmt: skip
            prompt = PROMPT.format(
                seller=seller.name, summary=seller.summary.strip(), company=profile.resolved_name,
                domain=profile.domain or "domain unknown", signals=signals, role=_role_block(role, spec),
                role_key=role, known=known_text,
            )  # fmt: skip
            answer: PeopleAnswer = self.run(prompt, PeopleAnswer, step="people").data
            found += [c.model_copy(update={"buying_role": role}) for c in answer.candidates]
        return found


def _rank(c: Candidate) -> tuple:
    newest = max((published_date(s) or date.min for s in c.sources), default=date.min)
    return (c.relevance, SENIORITY_RANK[c.seniority], len(c.sources), newest)


def _why_not(alt: Candidate, chosen: Candidate) -> str:
    if alt.relevance < chosen.relevance:
        return f"less focused on what we sell (relevance {alt.relevance} vs {chosen.relevance})"
    if SENIORITY_RANK[alt.seniority] < SENIORITY_RANK[chosen.seniority]:
        return f"less senior ({alt.seniority} vs {chosen.seniority})"
    if SENIORITY_RANK[alt.seniority] == SENIORITY_RANK[chosen.seniority] and alt.relevance == chosen.relevance:
        return "as strong; kept the person picked earlier or with more public sources"
    return "kept the person picked in an earlier run"


@dataclass
class Picks:
    chosen: list[Candidate] = field(default_factory=list)
    notes: dict[BuyingRole, str] = field(default_factory=dict)
    alternates: dict[BuyingRole, list[Alternate]] = field(default_factory=dict)


def pick_per_role(
    cands: list[Candidate], incumbents: dict[str, str] | None = None, excluded: set[str] | frozenset = frozenset()
) -> Picks:
    """One person per role. `incumbents` maps role -> person_key picked in an earlier run; that person
    keeps the role unless a candidate with higher relevance appears. `excluded` person_keys are skipped."""
    incumbents = incumbents or {}
    cands = sorted((c for c in cands if c.sources), key=_rank, reverse=True)
    out = Picks()
    used: set[str] = set(excluded)
    for role in ROLE_ORDER:
        pool = [c for c in cands if c.buying_role == role and person_key(c.name) not in used]
        eligible = [c for c in pool if c.relevance >= MIN_RELEVANCE]
        if not eligible:
            if pool:
                seen = "; ".join(f"{c.name} ({c.title}, relevance {c.relevance})" for c in pool)
                out.notes[role] = f"only weak matches found: {seen}"
            else:
                out.notes[role] = "not found for this role"
            continue
        best = eligible[0]
        held = next((c for c in eligible if person_key(c.name) == incumbents.get(role)), None)
        chosen = held if held and held.relevance >= best.relevance else best
        out.chosen.append(chosen)
        used.add(person_key(chosen.name))
        out.alternates[role] = [
            Alternate(name=a.name, title=a.title, relevance=a.relevance, why_not=_why_not(a, chosen),
                      source_url=a.sources[0].url)  # fmt: skip
            for a in eligible if a is not chosen
        ][:MAX_ALTERNATES]
    return out
