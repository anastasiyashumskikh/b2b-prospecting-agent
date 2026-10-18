import json

from prospect.models import (
    Alternate, CheckResult, CompanyProfile, CompanyResult, Contact, ContactContext, ContactResult, Drafts, Fact,
    RunOutput, Source,
)  # fmt: skip
from prospect.report import summarize, write_run


def contact(name, confidence="high", role="economic_buyer", linkedin=None) -> Contact:
    return Contact(
        name=name, title="VP Customer Care", company="Vodafone", buying_role=role, seniority="vp", relevance=5,
        relevance_reason="r", why="Owns care budget.", linkedin_url=linkedin,
        linkedin_status="matched" if linkedin else "not_found", sources=[Source(url="https://v.com/a", published="2026-04-01")],
        confidence=confidence, role_evidence="VP Customer Care: v.com (2026-04-01)",
    )  # fmt: skip


def result(name, basis="personal", attempts=1, **kw) -> ContactResult:
    fact = Fact(text="SuperTOBi solves 74% of queries.", source=Source(url="https://v.com/f", published="2026-05", opened=True))
    return ContactResult(
        contact=contact(name, **kw),
        context=ContactContext(summary=[fact], personalization=basis),
        drafts=Drafts(linkedin_note="x" * 287, email_subject="SuperTOBi and your agents",
                      email_body=" ".join(["word"] * 142), hooks=[fact.text]),
        check=CheckResult(mode="personal" if basis != "role" else "safe", basis=basis, attempts=attempts),
    )  # fmt: skip


PROFILE = CompanyProfile(
    input_name="Vodafone", resolved_name="Vodafone Group Plc", domain="vodafone.com", fit="strong",
    fit_reason="Large multilingual care operation.", fit_sources=[Source(url="https://v.com/fit")],
    signals=[Fact(text="Vodafone moves to proactive journeys.", source=Source(url="https://v.com/s", published="2026-04-14", opened=True))],
)  # fmt: skip

RESULTS = [
    CompanyResult(
        input_name="Vodafone", status="done", profile=PROFILE,
        contacts=[result("Ann Berg", linkedin="https://www.linkedin.com/in/ann-berg"),
                  result("Carl Dahl", "company", 2, confidence="medium", role="decision_maker"),
                  result("Eva Lind", "role", 4, role="champion")],
        alternates={"economic_buyer": [Alternate(name="Ivo Kask", title="COO", relevance=4,
                                                 why_not="less focused on what we sell (relevance 4 vs 5)",
                                                 source_url="https://v.com/i")]},
    ),
    CompanyResult(input_name="Mercury", status="needs_decision", reason="Ambiguous name, could be: Mercury Systems; Mercury Financial"),
    CompanyResult(input_name="Qwzxy", status="not_found", reason="No such company found"),
    CompanyResult(input_name="Acme", status="failed", reason="LLMError: timeout"),
]  # fmt: skip


def test_summary_counts():
    s = summarize(RESULTS, duration_s=600, cost_usd=2.5, searches=58)
    assert (s.companies, s.processed, s.needs_decision, s.not_found, s.failed) == (4, 1, 1, 1, 1)
    assert (s.contacts, s.contacts_high, s.passed_first_try) == (3, 2, 1)
    assert s.drafts_by_basis == {"personal": 1, "company": 1, "role": 1}


def test_run_dir_has_two_files(tmp_path):
    write_run(RESULTS, summarize(RESULTS, 600, 2.5, 58), tmp_path, "2026-10-18 21:00", "Concentrix iX Suite")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["report.md", "results.json"]


def test_results_json_roundtrip(tmp_path):
    write_run(RESULTS, summarize(RESULTS, 600, 2.5, 58), tmp_path, "2026-10-18 21:00", "Concentrix iX Suite")
    out = RunOutput.model_validate(json.loads((tmp_path / "results.json").read_text()))
    assert out.companies == RESULTS and out.summary.contacts == 3


def test_report_md_content(tmp_path):
    write_run(RESULTS, summarize(RESULTS, 600, 2.5, 58), tmp_path, "2026-10-18 21:00", "Concentrix iX Suite")
    md = (tmp_path / "report.md").read_text()
    for must in ["(287/300 characters)", "(142/150 words)", "## Needs your decision", "Mercury Systems",
                 "https://v.com/s", "[LinkedIn](https://www.linkedin.com/in/ann-berg)", "LinkedIn not opened by the agent by design",
                 "| Vodafone | [Ann Berg](#ann-berg) |",
                 "Economic buyer", "Decision-maker", "Champion", "Ivo Kask", "## Vodafone\n", "not available without LinkedIn login",
                 "general: no verified facts", "Qwzxy", "LLMError: timeout", "10 min"]:  # fmt: skip
        assert must in md, must
    assert "—" not in md


def test_rerender_matches_original(tmp_path):
    from prospect.report import rerender
    write_run(RESULTS, summarize(RESULTS, 600, 2.5, 58), tmp_path, "2026-10-18 21:00", "Concentrix iX Suite")
    before = (tmp_path / "report.md").read_text()
    assert rerender(tmp_path / "results.json").read_text() == before
