"""Runs the fixed step order per company. One company failing never stops the run."""

import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date
from typing import Protocol

from prospect.cards import CardStore, Pool
from prospect.inputs import CompanyInput
from prospect.llm import Runner
from prospect.models import BuyingRole, Candidate, CompanyProfile, CompanyResult, Contact, ContactResult
from prospect.seller import Seller
from prospect.steps.company import profile_company
from prospect.steps.context import gather_context
from prospect.steps.why import write_why
from prospect.steps.checks import check_with_retry
from prospect.steps.people import PeopleSource, Picks, WebSearchPeopleSource, pick_per_role
from prospect.steps.verify import assess, merge_candidates, person_key, verify_people


class Decider(Protocol):
    def decide(self, question: str, options: list[str]) -> str | None: ...


class BatchDecider:
    """Never asks: unclear companies are parked for the rep's decision."""

    def decide(self, question: str, options: list[str]) -> str | None:
        return None


class InteractiveDecider:
    def decide(self, question: str, options: list[str]) -> str | None:
        print(f"\n{question}", file=sys.stderr)
        for i, o in enumerate(options, 1):
            print(f"  {i}. {o}", file=sys.stderr)
        raw = input("Choose a number (Enter to skip): ").strip()
        return options[int(raw) - 1] if raw.isdigit() and 0 < int(raw) <= len(options) else None


@dataclass
class Ctx:
    """Everything one run shares across companies."""

    seller: Seller
    run: Runner
    decider: Decider
    today: date
    people: PeopleSource | None = None
    store: CardStore | None = None

    def __post_init__(self):
        self.people = self.people or WebSearchPeopleSource(self.run)


def run_company(c: CompanyInput, ctx: Ctx) -> CompanyResult:
    seller, run, decider, today = ctx.seller, ctx.run, ctx.decider, ctx.today
    p = None
    try:
        ans = profile_company(c, seller, run, today)
        if ans.outcome == "ambiguous":
            choice = decider.decide(f'"{c.name}" matches several companies. Which one?', ans.options)
            if choice is None:
                return CompanyResult(
                    input_name=c.name, status="needs_decision",
                    reason="Ambiguous name, could be: " + "; ".join(ans.options),
                )  # fmt: skip
            ans = profile_company(CompanyInput(choice, None), seller, run, today)
            if ans.profile:
                ans.profile.input_name = c.name
        if ans.outcome != "found" or not ans.profile:
            reason = "Still ambiguous: " + "; ".join(ans.options) if ans.outcome == "ambiguous" else None
            status = "needs_decision" if ans.outcome == "ambiguous" else "not_found"
            return CompanyResult(input_name=c.name, status=status, reason=reason or "No such company found")

        p = ans.profile
        if p.fit == "weak":
            q = f"{p.resolved_name} looks like a weak fit: {p.fit_reason}\nSearch for contacts anyway?"
            if decider.decide(q, ["yes", "no"]) != "yes":
                return CompanyResult(
                    input_name=c.name, status="needs_decision", reason=f"Weak fit: {p.fit_reason}", profile=p
                )
        pool = ctx.store.load_pool(p.resolved_name) if ctx.store else Pool()
        found = [] if all_roles_fresh(pool, p, ctx) else ctx.people.find(p, seller, pool.candidates)
        cands = merge_candidates(pool.candidates + found)
        picks, people, unconfirmed = choose_and_confirm(cands, pool, p, ctx)
        people = [x.model_copy(update={"why": write_why(x, p, seller, run)}) for x in people]
        if ctx.store:
            pool.candidates = cands
            pool.picked = {x.buying_role: person_key(x.name) for x in people}
            ctx.store.save_pool(p.resolved_name, pool)
        contacts, used_hooks = [], []
        for x in people:
            context = add_context(x, p, ctx)
            drafts, check = check_with_retry(x, context, p, seller, run, used_hooks)  # steps 4-5
            used_hooks += drafts.hooks
            contacts.append(ContactResult(contact=x, context=context, drafts=drafts, check=check))
        return CompanyResult(
            input_name=c.name, status="done", profile=p, contacts=contacts, unconfirmed=unconfirmed,
            role_notes=picks.notes, alternates=picks.alternates,
        )  # fmt: skip
    except Exception as e:  # one company must not stop the run
        return CompanyResult(input_name=c.name, status="failed", reason=f"{type(e).__name__}: {e}", profile=p)


def all_roles_fresh(pool: Pool, p: CompanyProfile, ctx: Ctx) -> bool:
    """Every buying role already has a person with a fresh card: no need to search for people again."""
    if not ctx.store or set(pool.picked) < set(ctx.seller.roles):
        return False
    names = {person_key(c.name): c.name for c in pool.candidates}
    return all(k in names and ctx.store.get(p.resolved_name, names[k]) for k in pool.picked.values())


def choose_and_confirm(
    cands: list[Candidate], pool: Pool, p: CompanyProfile, ctx: Ctx
) -> tuple[Picks, list[Contact], list[Contact]]:
    """Steps 1-2 together: pick per role, verify; if a pick drops out, pick the next one once more."""
    checked: dict[str, Contact | None] = {}
    skip: set[str] = set(pool.dropped)
    drop_notes: dict[BuyingRole, str] = {}
    parked: dict[str, Contact] = {}
    for _ in range(2):
        picks = pick_per_role(cands, pool.picked, skip)
        people, unconfirmed, dropped = confirm(picks.chosen, p, ctx, picks.notes, checked)
        parked |= {person_key(u.name): u for u in unconfirmed}
        out = set(dropped) | {person_key(u.name) for u in unconfirmed}
        drop_notes |= {c.buying_role: picks.notes[c.buying_role] for c in picks.chosen if person_key(c.name) in out}
        pool.dropped.update(dropped)
        if not out:
            break
        skip |= out
    filled = {x.buying_role for x in people}
    picks.notes |= {role: note for role, note in drop_notes.items() if role not in filled}
    return picks, people, list(parked.values())


def confirm(
    picks: list[Candidate], p: CompanyProfile, ctx: Ctx, notes: dict[BuyingRole, str], checked: dict[str, Contact | None]
) -> tuple[list[Contact], list[Contact], dict[str, str]]:
    """Step 2. Fresh cards are reused; everyone else is verified in one call. Fills notes for dropped roles.
    `checked` remembers verdicts within this run. Returns (confirmed, unconfirmed, dropped key -> reason)."""
    people: list[Contact] = []
    unconfirmed: list[Contact] = []
    dropped: dict[str, str] = {}
    to_check = []
    from_card: set[str] = set()
    for c in picks:
        key = person_key(c.name)
        card = ctx.store.get(p.resolved_name, c.name) if ctx.store else None
        if card:
            checked[key] = card.contact
            from_card.add(key)
        elif key not in checked:
            to_check.append(c)
    checks = verify_people(to_check, p, ctx.run, ctx.today) if to_check else {}
    for c in to_check:
        check = checks.get(person_key(c.name))
        checked[person_key(c.name)] = assess(c, check, ctx.today)
        if checked[person_key(c.name)] is None:
            dropped[person_key(c.name)] = (check and check.departure_evidence) or "no current public source"
    for c in picks:
        key = person_key(c.name)
        contact = checked[key]
        if contact is None:
            notes[c.buying_role] = f"{c.name} ({c.title}) dropped: {dropped.get(key, 'not confirmed')}"
        elif contact.confidence == "low":
            unconfirmed.append(contact)
            notes[c.buying_role] = f"{c.name} ({c.title}) found, but only in sources older than two years"
        else:
            people.append(contact)
            notes.pop(c.buying_role, None)
            if ctx.store and key not in from_card:  # never overwrite a fresh card: it may hold step 3 context
                ctx.store.put(p.resolved_name, contact)
    return people, unconfirmed, dropped


def add_context(contact: Contact, p: CompanyProfile, ctx: Ctx):
    """Step 3. Reuses the context on a fresh card; otherwise researches and saves it to the card."""
    card = ctx.store.get(p.resolved_name, contact.name) if ctx.store else None
    if card and card.context:
        return card.context
    context = gather_context(contact, p, ctx.seller, ctx.run, ctx.today)
    if ctx.store:
        ctx.store.put(p.resolved_name, contact, context)
    return context


def run_all(inputs: list[CompanyInput], ctx: Ctx, workers: int = 1) -> list[CompanyResult]:
    """Companies are independent, so a batch run can process several at once (the model calls are I/O)."""

    def one(i_c: tuple[int, CompanyInput]) -> CompanyResult:
        i, c = i_c
        print(f"[{i}/{len(inputs)}] {c.name}: started", file=sys.stderr)
        r = run_company(c, ctx)
        print(f"[{i}/{len(inputs)}] {c.name}: {r.status}", file=sys.stderr)
        return r

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        return list(pool.map(one, enumerate(inputs, 1)))  # keeps input order
