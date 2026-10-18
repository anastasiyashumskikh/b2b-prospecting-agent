"""Step 5. Checks: every contact ends with drafts that pass, never with a draft that needs fixing.

Ladder: personal draft -> two personal rewrites with every problem found so far -> safe draft (seller facts only)
-> seller.yaml fallback template, which passes the code rules by construction.
Code rules run first (cheap); the judge runs only on drafts that pass them.
"""

import re

from pydantic import BaseModel, Field

from prospect.config import BANNED_PHRASES, EMAIL_MAX_WORDS, NOTE_MAX_CHARS, SENDER_NAME_RESERVE, SUBJECT_MAX_WORDS
from prospect.llm import Runner
from prospect.models import CheckResult, CompanyProfile, Contact, ContactContext, Drafts
from prospect.seller import Seller
from prospect.steps.drafts import grounding_failures, prospect_facts, short_name, write_drafts
from prospect.steps.verify import first_name, person_key, ascii_tokens


class JudgeVerdict(BaseModel):
    specific: bool = Field(description="False if the text could be sent to another person at another company unchanged")
    specific_reason: str
    unsupported_claims: list[str] = Field(
        default_factory=list, description="Each claim not backed by a listed fact, or stretched beyond it, with why"
    )
    invented_sender_actions: list[str] = Field(
        default_factory=list, description="Things the sender claims to have done that the facts do not support"
    )


JUDGE = """You check a sales rep's outreach drafts to {name} at {company} before they are sent.

Facts about the prospect (the only allowed source for claims about them):
{facts}

Facts about the seller {seller} and its offers (the only allowed source for claims about the seller):
{seller_facts}

Drafts:
LinkedIn note: {note}
Email subject: {subject}
Email body:
{body}

1. specific: could this text go to a different person at a different company unchanged? If yes, specific = false.
2. unsupported_claims: split the drafts into claims. List every claim that is not in the facts above, or says more
   than the fact (a wider scope, a cause, a "most", an "every", a number or date that differs, a benefit of the
   seller's product that its facts do not state, what the prospect owns or needs). Not claims: a plain reaction
   ("nice result"), a question, and the sender's opinion that the product could fit, phrased as opinion
   ("I think iX Hero could be useful for your team").
3. invented_sender_actions: anything the sender claims to have done, seen or heard: "I watched", "I read",
   "I saw", "I noticed", "spoke with your team", "on our call". The drafts must state facts directly instead."""


def _numbers(text: str) -> set[str]:
    return {re.sub(r"\D", "", n) for n in re.findall(r"\d[\d,.]*", text)} - {""}


def rule_failures(d: Drafts, contact: Contact, context: ContactContext, profile: CompanyProfile, seller: Seller) -> list[str]:
    fails = []
    note_len = len(d.linkedin_note.replace("[Your name]", "x" * SENDER_NAME_RESERVE))
    if note_len > NOTE_MAX_CHARS:
        fails.append(f"LinkedIn note is {note_len} characters with a real sender name; the limit is {NOTE_MAX_CHARS}")
    if (n := len(d.email_body.split())) > EMAIL_MAX_WORDS:
        fails.append(f"email body is {n} words; the limit is {EMAIL_MAX_WORDS}")
    if (n := len(d.email_subject.split())) > SUBJECT_MAX_WORDS:
        fails.append(f"subject is {n} words; the limit is {SUBJECT_MAX_WORDS}")
    text = " ".join([d.linkedin_note, d.email_subject, d.email_body])
    low = text.lower()
    fails += [f'banned phrase "{p}"' for p in BANNED_PHRASES if p in low]
    if "—" in text:
        fails.append("long dash character used")
    if "!" in text or "..." in text or "…" in text:
        fails.append("exclamation mark or ellipsis used")
    first = first_name(contact.name)
    if first not in d.linkedin_note or first not in d.email_body:
        fails.append(f'first name "{first}" missing from the note or the email')
    corpus = " ".join(prospect_facts(context, profile) + [f.text for f in seller.facts] + seller.offers)
    unknown = sorted(_numbers(text) - _numbers(corpus))
    if unknown:
        fails.append("numbers not found in any fact: " + ", ".join(unknown))
    return fails


def judge(d: Drafts, contact: Contact, context: ContactContext, profile: CompanyProfile, seller: Seller, run: Runner) -> JudgeVerdict:
    prompt = JUDGE.format(
        name=contact.name, company=short_name(profile.resolved_name), seller=seller.company,
        facts="\n".join(f"- {f}" for f in prospect_facts(context, profile)) or "- (none)",
        seller_facts="\n".join(f"- {f.text}" for f in seller.facts) + "\n" + "\n".join(f"- offer: {o}" for o in seller.offers),
        note=d.linkedin_note, subject=d.email_subject, body=d.email_body,
    )  # fmt: skip
    return run(prompt, JudgeVerdict, step="judge").data


def drafts_basis(d: Drafts, contact: Contact) -> str:
    """What the final drafts rest on, judged by the facts they actually use."""
    surname = person_key(contact.name).split("-")[-1]
    if any(surname in ascii_tokens(h.replace("ß", "ss")) for h in d.hooks):
        return "personal"
    return "company" if d.hooks else "role"


def template_drafts(contact: Contact, profile: CompanyProfile, seller: Seller) -> Drafts:
    fill = {"first_name": first_name(contact.name), "company": short_name(profile.resolved_name)}
    fb = seller.fallback
    return Drafts(
        linkedin_note=fb.linkedin_note.format(**fill), email_subject=fb.email_subject.format(**fill),
        email_body=fb.email_body.format(**fill), hooks=[],
    )  # fmt: skip


def check_with_retry(
    contact: Contact, context: ContactContext, profile: CompanyProfile, seller: Seller, run: Runner,
    used_hooks: list[str] | None = None,
) -> tuple[Drafts, CheckResult]:  # fmt: skip
    fixed: list[str] = []
    feedback: list[str] | None = None
    for attempt, safe in enumerate([False, False, False, True], start=1):
        d = write_drafts(contact, context, profile, seller, run, used_hooks, feedback, safe=safe)
        problems = rule_failures(d, contact, context, profile, seller)
        problems += grounding_failures(d, context, profile, seller, safe=safe)
        reason = ""
        if not problems:
            v = judge(d, contact, context, profile, seller, run)
            reason = v.specific_reason
            problems = [f"unsupported claim: {c}" for c in v.unsupported_claims]
            problems += [f"invented sender action: {a}" for a in v.invented_sender_actions]
            if not safe and not v.specific:
                problems.append(f"reads as generic: {v.specific_reason}")
        if not problems:
            basis = "role" if safe else drafts_basis(d, contact)
            return d, CheckResult(mode="safe" if safe else "personal", basis=basis, attempts=attempt, fixed=fixed,
                                  judge_reason=reason)  # fmt: skip
        fixed += problems
        feedback = fixed  # cumulative, so a rewrite does not bring back an earlier mistake
    return template_drafts(contact, profile, seller), CheckResult(mode="template", basis="role", attempts=5, fixed=fixed)
