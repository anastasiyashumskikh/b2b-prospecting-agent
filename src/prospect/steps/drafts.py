"""Step 4. Drafts: a LinkedIn connection note and a cold email that sound like a person, not a campaign.

Every hook must be a fact from the contact card or the company signals, every claim about the seller a
fact from seller.yaml, every offer one of seller.yaml's offers. The code checks hooks and seller facts.
"""

import re

from prospect.llm import Runner
from prospect.models import CompanyProfile, Contact, ContactContext, Drafts
from prospect.seller import Seller
from prospect.steps.verify import first_name

ROLE_ANGLE = {
    "economic_buyer": "cost and scale of customer service: volume, cost per contact, results at scale",
    "decision_maker": "how AI fits their current systems and how they keep it safe and governed",
    "champion": "the agents' day-to-day: handling the hard queries, handle time, quality",
}

PROMPT = """You write first-touch outreach for a sales rep at {company}. The rep sends it; you draft.

Recipient: {name}, {title} at {prospect}.
Why them: {why}
Angle for their role: {angle}

THE ONE RULE: you may say only what is written below. Every sentence about {first_name} or {prospect} must restate
one numbered fact P1, P2, ... in its own meaning: same scope, same time, same numbers, nothing added, two facts never
joined into one claim. Every sentence about {company} must restate one fact S1, S2, ... the same way, with no extra
benefit, use case or result. Anything else in the text may only be: a greeting, who is writing, a short reaction
("nice result", "big move"), a question, your opinion that the product could fit phrased as opinion ("I think iX
Hero could be useful for your team"), or an offer from the list. You do not know what they own, need, feel or plan:
if you want to connect a fact to their work, ask a question.

Facts about them and their company:
{facts}

Facts about {company}:
{seller_facts}

Offers (propose only these):
{offers}
{colleagues}{feedback}
How a real salesperson writes it, in this order:
1. Who is writing: "I'm [Your name] from {company}."
2. Their fact, stated directly: "In December you announced ...", "Vodafone's FY26 results show ...". Do not claim
   anything the sender did: no "I watched", "I read", "I saw", "I noticed", "I listened". "Congrats on the new role"
   only if a fact is a recent appointment. An event from months ago is told in the past tense with its month.
3. If useful, one question about that fact, the kind a peer would ask. No stock praise ("nice result", "big move",
   "impressive", "strong numbers"): a reaction, if any, must be about this specific fact.
4. What {company} does, in one sentence from the ONE S fact that matters most for this angle. Name one capability,
   not a list. Your opinion that it could fit is optional; if you give it, tie it to their fact.
5. A direct next step from the offers, tied to their situation. Ask for a time in your own words.

LinkedIn note: at most 270 characters including spaces (the sender's real name replaces [Your name]). First name, who is writing, their fact, what we do, the offer
in a few words. No links.
Email: subject 3-6 words about their situation, no sales words. Body 70-120 words, never more than 150 words, short
paragraphs. Start "Hi {first_name},". End with "Best,\n[Your name]". The product name appears at most once and never
in the first paragraph.

Plain conversational English (B2-C1): contractions are fine, mostly short sentences, never three sentences in a row
starting with "I". Do not use: the long dash character, "I hope this finds you well", "I came across your profile",
"I wanted to reach out", "touch base", "quick call", "synergy", "leverage", "game-changer", "revolutionize",
"cutting-edge", "world-class", "Furthermore", "Moreover", "Additionally", "thrilled", "excited", "passionate",
"what stands out", "not just X but Y", "exactly what you need", exclamation marks, "...", hedges like "if this is of
interest" or "should you be open to". Do not promise anything that is not in the offers.

Before you answer, go through your drafts sentence by sentence and match each one to a fact number, or to one of the
allowed kinds above. Rewrite or delete any sentence that does not match.

Return hooks = the exact texts of the P facts you used, seller_facts = the exact texts of the S facts you used."""


SAFE_FACTS = """(none for this draft) Write without any claim about them or their company beyond their name, title and
company name: no projects, results, news, quotes, responsibilities or needs. Skip point 2 and the question in
point 3. Keep the email body to 60-90 words. Return hooks as an empty list."""


LEGAL_SUFFIXES = r"(,?\s+(group|plc|se|ag|nv|n\.v\.|sa|s\.a\.|inc\.?|ltd\.?|limited|llc|corp\.?|gmbh|holding|holdings|ab|asa|oyj|spa|s\.p\.a\.))+$"


def short_name(company: str) -> str:
    """How people write the company in an email: "Vodafone Group Plc" -> "Vodafone",
    "IKEA (Inter IKEA Group franchisor; ...)" -> "IKEA"."""
    plain = re.sub(r"\s*\(.*?\)", "", company)
    plain = re.split(r",\s*(part of|a subsidiary of|owned by)\b", plain, flags=re.I)[0].strip() or company.strip()
    return re.sub(LEGAL_SUFFIXES, "", plain, flags=re.I) or plain


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().rstrip(".").casefold()


def prospect_facts(context: ContactContext, profile: CompanyProfile) -> list[str]:
    """What drafts may say about the prospect: page facts only. The pain line is the agent's reading, so it
    stays in the context for the rep and never goes into a draft."""
    return [f.text for f in context.summary] + [s.text for s in profile.signals]


def grounding_failures(
    d: Drafts, context: ContactContext, profile: CompanyProfile, seller: Seller, safe: bool = False
) -> list[str]:
    """Hooks must be prospect facts and seller claims must be seller.yaml facts. Returns what is not.
    Safe drafts must use no prospect facts at all."""
    known = {_norm(f) for f in prospect_facts(context, profile)}
    ours = {_norm(f.text) for f in seller.facts}
    fails = [f"seller claim is not in seller.yaml: {s}" for s in d.seller_facts if _norm(s) not in ours]
    if safe:
        return fails + (["safe drafts must not use facts about the prospect"] if d.hooks else [])
    fails += [f"hook is not a known fact: {h}" for h in d.hooks if _norm(h) not in known]
    if not d.hooks:
        fails.append("no hook: the drafts must use at least one fact about the prospect")
    return fails


def write_drafts(
    contact: Contact, context: ContactContext, profile: CompanyProfile, seller: Seller, run: Runner,
    used_hooks: list[str] | None = None, feedback: list[str] | None = None, safe: bool = False,
) -> Drafts:  # fmt: skip
    """safe=True writes without any fact about the person or company: only their name, title, company name,
    the role angle and the seller's facts and offers. Used when personal drafts keep failing the checks."""
    colleagues = (
        "\nAlready used in messages to colleagues at the same company (pick a different hook if you can):\n"
        + "\n".join(f"- {h}" for h in used_hooks) + "\n"
    ) if used_hooks else ""  # fmt: skip
    fix = (
        "\nEarlier drafts failed these checks. Change only what they point at, keep the rest, and do not bring any of "
        "them back:\n" + "\n".join(f"- {f}" for f in feedback) + "\n"
    ) if feedback else ""  # fmt: skip
    prompt = PROMPT.format(
        company=seller.company, name=contact.name, first_name=first_name(contact.name), title=contact.title,
        prospect=short_name(profile.resolved_name), why=contact.why, angle=ROLE_ANGLE[contact.buying_role],
        facts=SAFE_FACTS if safe else "\n".join(f"P{i}. {f}" for i, f in enumerate(prospect_facts(context, profile), 1)),
        seller_facts="\n".join(f"S{i}. {f.text}" for i, f in enumerate(seller.facts, 1)),
        offers="\n".join(f"- {o}" for o in seller.offers), colleagues=colleagues, feedback=fix,
    )  # fmt: skip
    return run(prompt, Drafts, step="drafts").data
