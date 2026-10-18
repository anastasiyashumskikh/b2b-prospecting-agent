"""Step 3. Context: what this person has said or done in public, and what that means for the deal.

The model searches; the code keeps only recent, real sources, keeps the summary at 2-4 facts, and
downgrades "personal" when no fact actually names the person.
"""

from datetime import date

from prospect.config import STALE_SOURCE_DAYS
from prospect.llm import Runner
from prospect.models import CompanyProfile, Contact, ContactContext, Fact, published_date
from prospect.seller import Seller
from prospect.steps.verify import ascii_tokens, person_key, trusted_fact

MIN_FACTS, MAX_FACTS = 2, 4

PROMPT = """Today is {today}. A sales rep selling {seller} will write to {name}, {title} at {company}.
Why this person: {why}
Their likely pain as {role_label}: {pain}
What we know about the company now:
{signals}

Find public context that helps the rep personalize the first message:
- recent activity: interviews, podcasts, conference talks, articles they wrote, quotes in press releases and news;
- role changes: a recent appointment or promotion;
- company news that touches their area.
Prefer the last 12 months; skip anything older than two years.

Use only facts from pages you opened and read yourself; set source.opened = true for them. Something seen only
in search results does not count. LinkedIn pages cannot be opened, so LinkedIn posts cannot be used.

Return:
- summary: 2-4 facts, each ONE plain sentence of at most 30 words, stating only what the page says, with its
  source URL and page date. Facts where {name} is named come first. No notes about how you searched.
- pain: one sentence of at most 30 words on how the pain above shows in this company's facts, with the
  source of that fact. If no fact shows it, leave pain empty.
- personalization: "personal" if at least one fact is {name}'s own words or action, "company" if facts are
  only about the company, "role" if you found nothing beyond the title.
Contact-data sites (RocketReach, ZoomInfo and similar) are not sources. Never invent a fact."""


def _usable(f: Fact, today: date) -> bool:
    d = published_date(f.source)
    return trusted_fact(f) and (d is None or (today - d).days <= STALE_SOURCE_DAYS)


def _names_person(f: Fact, name: str) -> bool:
    surname = person_key(name).split("-")[-1]
    return surname in ascii_tokens(f.text.replace("ß", "ss"))


def gather_context(contact: Contact, profile: CompanyProfile, seller: Seller, run: Runner, today: date) -> ContactContext:
    spec = seller.roles[contact.buying_role]
    prompt = PROMPT.format(
        today=today.isoformat(), seller=seller.name, name=contact.name, title=contact.title,
        company=profile.resolved_name, why=contact.why, role_label=spec.label, pain=spec.pain.strip(),
        signals="\n".join(f"- {s.text}" for s in profile.signals) or "- (no recent signals found)",
    )  # fmt: skip
    ans: ContactContext = run(prompt, ContactContext, step="context").data

    summary = [f for f in ans.summary if _usable(f, today)][:MAX_FACTS]
    urls = {f.source.url for f in summary}
    for s in profile.signals:  # top up with company signals so the rep always has something real
        if len(summary) >= MIN_FACTS:
            break
        if s.source.url not in urls:
            summary.append(s)
            urls.add(s.source.url)

    if any(_names_person(f, contact.name) for f in summary):
        level = "personal"
    else:
        level = "company" if summary else "role"
    pain = ans.pain if ans.pain and _usable(ans.pain, today) else None
    return ContactContext(summary=summary, pain=pain, personalization=level)
