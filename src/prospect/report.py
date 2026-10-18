"""Step 6. Output: runs/<date-time>/report.md (read on GitHub, no code needed) and results.json (for a CRM)."""

from pathlib import Path
from urllib.parse import quote_plus

from prospect.config import EMAIL_MAX_WORDS, NOTE_MAX_CHARS
from prospect.models import CompanyResult, ContactResult, Fact, RunOutput, RunSummary, Source
from prospect.steps.drafts import short_name

ROLE_LABEL = {"economic_buyer": "Economic buyer", "decision_maker": "Decision-maker", "champion": "Champion"}
BASIS_LABEL = {
    "personal": "personal: built on this person's own words or actions",
    "company": "company: built on company news",
    "role": "general: no verified facts about this person or company were found, so it uses only seller facts",
}


BASIS_SHORT = {"personal": "personal", "company": "company news", "role": "general"}


def summarize(results: list[CompanyResult], duration_s: float, cost_usd: float, searches: int) -> RunSummary:
    contacts = [c for r in results for c in r.contacts]
    by_basis = {"personal": 0, "company": 0, "role": 0}
    for c in contacts:
        if c.check:
            by_basis[c.check.basis] += 1
    count = lambda status: sum(r.status == status for r in results)  # noqa: E731
    return RunSummary(
        companies=len(results), processed=count("done"), needs_decision=count("needs_decision"),
        failed=count("failed"), not_found=count("not_found"), contacts=len(contacts),
        contacts_high=sum(c.contact.confidence == "high" for c in contacts), drafts_by_basis=by_basis,
        passed_first_try=sum(bool(c.check and c.check.attempts == 1) for c in contacts),
        duration_s=duration_s, cost_usd=cost_usd, searches=searches,
    )  # fmt: skip


def _link(s: Source) -> str:
    label = s.title or s.url.split("/")[2]
    return f"[{label}]({s.url})" + (f" ({s.published})" if s.published else "")


def _fact(f: Fact) -> str:
    return f"- {f.text} {_link(f.source)}"


def _contact(c: ContactResult) -> list[str]:
    p = c.contact
    search = "https://www.linkedin.com/search/results/people/?keywords=" + quote_plus(f"{p.name} {p.company}")
    li = (f"[LinkedIn]({p.linkedin_url})" if p.linkedin_status == "matched"
          else f"LinkedIn not opened by the agent by design ([search]({search}))")  # fmt: skip
    out = [
        f"### {p.name}", "",
        f"**{p.title}** · {ROLE_LABEL[p.buying_role]} · confidence {p.confidence} · {li}", "",
        f"Why this person: {p.why}", "",
        f"Current role: {p.role_evidence}. Sources: " + ", ".join(_link(s) for s in p.sources), "",
    ]  # fmt: skip
    if c.context:
        out += ["**Context**", ""] + [_fact(f) for f in c.context.summary]
        if c.context.pain:
            out += [f"- Likely pain (agent's reading, not used in the drafts): {c.context.pain.text}"]
        out += [f"- Shared connections: {c.context.shared_connections}", ""]
    if c.drafts and c.check:
        d = c.drafts
        out += [
            f"**LinkedIn note** ({len(d.linkedin_note)}/{NOTE_MAX_CHARS} characters)", "", f"> {d.linkedin_note}", "",
            f"**Email** ({len(d.email_body.split())}/{EMAIL_MAX_WORDS} words)", "", f"Subject: {d.email_subject}", "",
            "```", d.email_body, "```", "",
            f"Drafts rest on: {BASIS_LABEL[c.check.basis]}. Checks passed on attempt {c.check.attempts}"
            + (f" after fixing {len(c.check.fixed)} problem(s)." if c.check.fixed else "."), "",
        ]  # fmt: skip
    return out


def _company(r: CompanyResult) -> list[str]:
    p = r.profile
    title = short_name(p.resolved_name) if p else r.input_name
    out = [f"## {title}", ""]
    if p and title.casefold() != r.input_name.casefold():
        out += [f"Input: {r.input_name} → {title}", ""]
    if p:
        out += [f"**Fit: {p.fit}.** {p.fit_reason} " + ", ".join(_link(s) for s in p.fit_sources), ""]
        out += ["**Why now**", ""] + ([_fact(s) for s in p.signals] or ["- No dated signals from the last 12 months."]) + [""]
    for c in r.contacts:
        out += _contact(c)
    if r.role_notes:
        out += ["**Roles without a contact**", ""]
        out += [f"- {ROLE_LABEL[role]}: {note}" for role, note in r.role_notes.items()]
    if r.alternates:
        out += ["", "**Other candidates per role** (not verified)", ""]
        for role, alts in r.alternates.items():
            out += [f"- {ROLE_LABEL[role]}: {a.name}, {a.title}, {a.why_not} ([source]({a.source_url}))" for a in alts]
    if r.unconfirmed:
        out += ["", "**Found but not confirmed** (only sources older than two years)", ""]
        out += [f"- {c.name}, {c.title} ({ROLE_LABEL[c.buying_role]})" for c in r.unconfirmed]
    return out + ["", "---", ""]


def render_markdown(results: list[CompanyResult], s: RunSummary, started_at: str, seller: str) -> str:
    b = s.drafts_by_basis
    lines = [
        f"# Prospecting run, {started_at}", "",
        f"Seller: {seller}. Every contact is ready for the rep to review and send; nothing was sent.", "",
        "| Companies | Processed | Need your decision | Not found / failed | Contacts (high confidence) "
        "| Drafts: personal / company / general | Passed checks first try | Time | Model cost |",
        "|---|---|---|---|---|---|---|---|---|",
        f"| {s.companies} | {s.processed} | {s.needs_decision} | {s.not_found} / {s.failed} "
        f"| {s.contacts} ({s.contacts_high}) | {b['personal']} / {b['company']} / {b['role']} "
        f"| {s.passed_first_try} of {s.contacts} | {s.duration_s / 60:.0f} min | ${s.cost_usd:.2f} |", "",
        "Model cost is at API list price; with a Claude subscription there is no per-run charge, the run uses its "
        f"limits. Web searches in this run: {s.searches}"
        + (" (every role had a fresh contact card from earlier runs, so people were not searched again)." if s.searches == 0 else "."),
        "",
    ]  # fmt: skip
    done = [r for r in results if r.status == "done" and r.contacts]
    if done:
        lines += ["| Company | Contact | Title | Role | Confidence | Drafts rest on |", "|---|---|---|---|---|---|"]
        for r in done:
            for c in r.contacts:
                p = c.contact
                anchor = "-".join(p.name.lower().split()).replace(".", "")
                basis = c.check.basis if c.check else ""
                lines.append(f"| {short_name(r.profile.resolved_name)} | [{p.name}](#{anchor}) | {p.title} "
                             f"| {ROLE_LABEL[p.buying_role]} | {p.confidence} | {BASIS_SHORT.get(basis, basis)} |")  # fmt: skip
        lines += [""]
    parked = [r for r in results if r.status != "done"]
    if parked:
        lines += ["## Needs your decision", ""]
        lines += [f"- **{r.input_name}** ({r.status.replace('_', ' ')}): {r.reason}" for r in parked]
        lines += [""]
    for r in results:
        if r.status == "done":
            lines += _company(r)
    return "\n".join(lines)


def write_run(results: list[CompanyResult], s: RunSummary, run_dir: Path, started_at: str, seller: str) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "report.md").write_text(render_markdown(results, s, started_at, seller))
    out = RunOutput(started_at=started_at, seller=seller, summary=s, companies=results)
    (run_dir / "results.json").write_text(out.model_dump_json(indent=2))


def rerender(results_json: Path) -> Path:
    """Rebuild report.md from a run's results.json, e.g. after a change to the report layout."""
    out = RunOutput.model_validate_json(results_json.read_text())
    md = results_json.parent / "report.md"
    md.write_text(render_markdown(out.companies, out.summary, out.started_at, out.seller))
    return md
