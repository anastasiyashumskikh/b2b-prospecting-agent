"""Step 0. Company: which company is this, does it fit the seller's ICP, why might it care now."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from prospect.config import MAX_SIGNALS, SIGNAL_MAX_AGE_DAYS
from prospect.inputs import CompanyInput
from prospect.llm import Runner
from prospect.models import CompanyProfile, published_date
from prospect.steps.verify import trusted_fact
from prospect.seller import Seller


class CompanyAnswer(BaseModel):
    outcome: Literal["found", "ambiguous", "not_found"]
    options: list[str] = Field(default_factory=list, description="Distinct companies the name could mean, if ambiguous")
    profile: CompanyProfile | None = Field(None, description="Filled only when outcome is found")


PROMPT = """Today is {today}. A sales rep selling {seller} wants to prospect the company "{name}".{domain_hint}

1. Identify the company. Find its official website domain and make sure it is the company meant.
   - The name may contain a typo: if one company is clearly meant, use its correct name.
   - If the name fits several distinct companies and nothing tells them apart, set outcome "ambiguous"
     and list them in options (name plus a short distinguisher, e.g. "Mercury Systems (US defense electronics)").
   - If no such company can be found, set outcome "not_found". Do not invent one.

2. Rate its fit with the seller's ideal customer profile:
   {icp}
   - strong: a large customer support operation (thousands of agents, own or outsourced contact centers,
     millions of customer interactions) AND an industry from the profile AND at least one recent signal below.
   - partial: a large support operation, but the industry is outside the profile or there is no recent signal;
     or the size of support can only be inferred indirectly.
   - weak: a small company (roughly under 500 employees), no mass customer support, or a direct competitor
     of Concentrix (customer-experience BPOs such as Teleperformance, TTEC, Foundever, TaskUs).
   Give fit_reason in one or two sentences and fit_sources with URLs.

3. Find 2-3 signals: dated public events from the last 12 months that give a reason to talk now, e.g.
   hiring for customer support, expansion into new markets or languages, a change in customer-experience
   leadership, executives talking about AI or customer service on investor calls, public complaints about
   support quality, launching their own AI assistant. Each signal: one sentence, the source URL, the page date.
   Open each signal's page and read it there; set source.opened = true only then. Something seen only in search
   results does not count. LinkedIn pages cannot be opened, so they cannot be signals.
   Skip anything older than 12 months or without a visible date.

Fill profile.input_name with "{name}" and profile.resolved_name with the company's proper name only, as it would
appear in an email (e.g. "IKEA", "Vodafone Group Plc"): no explanations or brackets; put context in fit_reason."""


def profile_company(c: CompanyInput, seller: Seller, run: Runner, today: date) -> CompanyAnswer:
    domain_hint = f" Its website domain is {c.domain}; trust it." if c.domain else ""
    prompt = PROMPT.format(
        today=today.isoformat(), seller=seller.name, name=c.name, domain_hint=domain_hint, icp=seller.icp
    )
    ans: CompanyAnswer = run(prompt, CompanyAnswer, step="company").data
    if ans.outcome == "found" and ans.profile:
        p = ans.profile
        fresh = [
            s for s in p.signals
            if trusted_fact(s) and (d := published_date(s.source)) and (today - d).days <= SIGNAL_MAX_AGE_DAYS
        ]  # fmt: skip
        ans.profile = p.model_copy(update={"input_name": c.name, "signals": fresh[:MAX_SIGNALS]})
    elif ans.outcome == "found":
        ans = CompanyAnswer(outcome="not_found")
    return ans
