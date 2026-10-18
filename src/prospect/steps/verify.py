"""Step 2. Merge and verify: one card per person, still in the role now, how sure we are.

The model searches for current evidence; the code decides confidence from dates and domains.
"""

import re
import unicodedata
from datetime import date
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from prospect.config import DIRECTORY_DOMAINS, FRESH_SOURCE_DAYS, STALE_SOURCE_DAYS
from prospect.llm import Runner
from prospect.models import Candidate, CompanyProfile, Contact, Fact, Source, published_date


class RoleCheck(BaseModel):
    name: str
    still_there: Literal["yes", "no", "unclear"]
    current_title: str
    evidence: list[Source] = Field(default_factory=list, description="Most recent dated pages confirming the role")
    departure_evidence: str | None = Field(None, description="What shows they left, with URL, if anything")
    title_confirmed: bool = Field(
        True, description="False if the newest dated source gives a different title than the one we have"
    )
    linkedin_confirmed: bool = Field(
        False, description="A search result showed this person's linkedin.com/in profile with their name and company"
    )


class VerifyAnswer(BaseModel):
    checks: list[RoleCheck]


PROMPT = """Today is {today}. For each person below, check whether they work at {company} ({domain}) in this role now.

{people}

For each person:
- Search for the most recent dated public page that shows them in this role at {company} (news, interviews,
  conference agendas, company pages). An announced future talk counts as current. Put such pages in evidence.
- If the newest dated source gives them a different title than the one above, set title_confirmed = false
  and put that newer title in current_title.
- Look for signs they left: "former", "ex-", news of a move, a new employer. If found, still_there = "no" and
  describe it with the URL in departure_evidence. If nothing recent confirms or denies, still_there = "unclear".
- linkedin_confirmed = true only if a search result shows their linkedin.com/in/ profile with their name and
  {company}. Do not open linkedin.com pages.
- Contact-data sites (RocketReach, ZoomInfo, TheOfficialBoard, Apollo and similar) do not count as evidence.
Return one check per person, with the name exactly as given."""


def ascii_tokens(text: str) -> list[str]:
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.findall(r"[a-z0-9]+", plain)


HONORIFICS = {"dr", "prof", "mr", "mrs", "ms", "sir", "dame"}


def first_name(name: str) -> str:
    """How to greet them: "Dr. Christian Niedworok" -> "Christian"."""
    words = re.sub(r"\(.*?\)", " ", name).split()
    real = [w for w in words if w.strip(".").casefold() not in HONORIFICS]
    return (real or words)[0]


def person_key(name: str) -> str:
    """Stable ASCII key within a company: first initial + surname. Accents, case, middle initials,
    nicknames in brackets and short forms (Bev / Beverley, Tom / Thomas) do not matter."""
    tokens = [t for t in ascii_tokens(re.sub(r"\(.*?\)", " ", name)) if len(t) > 1 and t not in HONORIFICS]
    return f"{tokens[0][0]}-{tokens[-1]}" if len(tokens) > 1 else "".join(tokens)


def slug(text: str) -> str:
    return "-".join(ascii_tokens(text))


def _domain(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("www.")


def is_directory(url: str) -> bool:
    d = _domain(url)
    return any(d == x or d.endswith("." + x) for x in DIRECTORY_DOMAINS)


def trusted_fact(f: Fact) -> bool:
    """A fact may go into context or drafts only from a page the agent opened and read itself.
    Search snippets, LinkedIn pages (never opened) and contact-data sites do not qualify."""
    host = urlparse(f.source.url).netloc.lower()
    linkedin = host == "linkedin.com" or host.endswith(".linkedin.com")
    return f.source.opened and not linkedin and not is_directory(f.source.url)


def merge_candidates(cands: list[Candidate]) -> list[Candidate]:
    """Same person found twice becomes one candidate: best-rated copy, all sources."""
    merged: dict[str, Candidate] = {}
    for c in cands:
        key = person_key(c.name)
        if key not in merged:
            merged[key] = c
            continue
        keep, other = sorted([merged[key], c], key=lambda x: x.relevance, reverse=True)
        urls = {s.url for s in keep.sources}
        sources = keep.sources + [s for s in other.sources if s.url not in urls]
        merged[key] = keep.model_copy(update={"sources": sources, "linkedin_url": keep.linkedin_url or other.linkedin_url})
    return list(merged.values())


def verify_people(people: list[Candidate], profile: CompanyProfile, run: Runner, today: date) -> dict[str, RoleCheck]:
    """One search call for all of a company's picks. Returns checks keyed by person_key."""
    lines = "\n".join(
        f"- {c.name}, {c.title}. Found on: " + ", ".join(s.url for s in c.sources) for c in people
    )  # fmt: skip
    prompt = PROMPT.format(
        today=today.isoformat(), company=profile.resolved_name, domain=profile.domain or "domain unknown", people=lines
    )
    answer: VerifyAnswer = run(prompt, VerifyAnswer, step="verify").data
    return {person_key(ch.name): ch for ch in answer.checks}


def check_linkedin(url: str | None, name: str, confirmed: bool) -> Literal["matched", "not_found"]:
    if not url:
        return "not_found"
    u = urlparse(url)
    host = u.netloc.lower()
    if not (host == "linkedin.com" or host.endswith(".linkedin.com")) or not u.path.startswith("/in/"):
        return "not_found"
    # A surname in the URL is not enough: a namesake at another company has the same slug (manual check, 18.10).
    return "matched" if confirmed else "not_found"


def assess(c: Candidate, check: RoleCheck | None, today: date) -> Contact | None:
    """None = drop (left, 'former', or no real source). Otherwise a Contact with confidence."""
    titles = [c.title] + ([check.current_title] if check else [])
    if (check and check.still_there == "no") or any(re.search(r"\b(former|ex-)", t.lower()) for t in titles):
        return None
    seen: set[str] = set()
    sources = []
    for s in c.sources + (check.evidence if check else []):
        if s.url not in seen and not is_directory(s.url):
            seen.add(s.url)
            sources.append(s)
    if not sources:
        return None

    dates = [published_date(s) for s in sources]
    ages = [max((today - d).days, 0) for d in dates if d]  # a future talk date counts as today
    undated = any(d is None for d in dates)
    if ages and not undated and min(ages) > STALE_SOURCE_DAYS:
        confidence = "low"
    elif len({_domain(s.url) for s in sources}) >= 2 or (ages and min(ages) <= FRESH_SOURCE_DAYS):
        confidence = "high"
    else:
        confidence = "medium"
    if confidence == "high" and (check is None or check.still_there == "unclear" or not check.title_confirmed):
        confidence = "medium"

    newest = max(sources, key=lambda s: published_date(s) or date.min)
    evidence = f"{check.current_title if check else c.title}: {_domain(newest.url)}"
    evidence += f" ({newest.published})" if newest.published else " (undated)"
    title = check.current_title if check and not check.title_confirmed and check.current_title else c.title
    return Contact(
        **c.model_dump(exclude={"sources", "title"}),
        title=title,
        sources=sources,
        confidence=confidence,
        linkedin_status=check_linkedin(c.linkedin_url, c.name, bool(check and check.linkedin_confirmed)),
        role_evidence=evidence,
    )
