from datetime import date

from conftest import FakeRunner, ScriptedDecider
from prospect.inputs import CompanyInput
from prospect.llm import LLMError
from prospect.cards import CardStore
from prospect import pipeline
from prospect.models import Candidate, CheckResult, CompanyProfile, ContactContext, Drafts, Source
from prospect.pipeline import BatchDecider, Ctx, run_all, run_company
from prospect.steps.company import CompanyAnswer
from prospect.steps.people import PeopleAnswer
from prospect.steps.verify import RoleCheck, VerifyAnswer
from prospect.steps.why import WhyAnswer

TODAY = date(2026, 10, 18)


def found(name="Mercury Systems", fit="strong") -> CompanyAnswer:
    p = CompanyProfile(input_name=name, resolved_name=name, domain="x.com", fit=fit, fit_reason="because")
    return CompanyAnswer(outcome="found", profile=p)


NOBODY = PeopleAnswer(candidates=[])
CTX = [ContactContext(summary=[], personalization="role")] * 3
WHY = [WhyAnswer(why="Owns the care budget.")]
DR = [Drafts(linkedin_note="n", email_subject="s", email_body="b")] * 3


def ctx(seller, run, decider=None):
    return Ctx(seller, run, decider or BatchDecider(), TODAY)


AMBIGUOUS = CompanyAnswer(outcome="ambiguous", options=["Mercury Financial", "Mercury Systems"])


def test_ambiguous_name_batch_needs_decision(seller):
    run = FakeRunner({"company": [AMBIGUOUS]})
    r = run_company(CompanyInput("Mercury", None), ctx(seller, run, BatchDecider()))
    assert r.status == "needs_decision"
    assert "Mercury Financial" in r.reason and "Mercury Systems" in r.reason


def test_ambiguous_name_interactive_uses_choice(seller):
    run = FakeRunner({"company": [AMBIGUOUS, found()], "people": [NOBODY] * 3})
    r = run_company(CompanyInput("Mercury", None), ctx(seller, run, ScriptedDecider(["Mercury Systems"])))
    assert r.status == "done" and r.input_name == "Mercury"
    assert "Mercury Systems" in run.prompts["company"][1]


def test_weak_fit_batch_deferred(seller):
    run = FakeRunner({"company": [found(fit="weak")]})
    r = run_company(CompanyInput("Tiny Co", None), ctx(seller, run, BatchDecider()))
    assert r.status == "needs_decision" and "because" in r.reason and r.profile is not None


def test_weak_fit_interactive_declined(seller):
    run = FakeRunner({"company": [found(fit="weak")]})
    r = run_company(CompanyInput("Tiny Co", None), ctx(seller, run, ScriptedDecider(["no"])))
    assert r.status == "needs_decision"


def test_weak_fit_interactive_accepted(seller):
    run = FakeRunner({"company": [found(fit="weak")], "people": [NOBODY] * 3})
    r = run_company(CompanyInput("Tiny Co", None), ctx(seller, run, ScriptedDecider(["yes"])))
    assert r.status == "done"


def test_company_not_found(seller):
    run = FakeRunner({"company": [CompanyAnswer(outcome="not_found")]})
    r = run_company(CompanyInput("Qwzxy Ltd", None), ctx(seller, run, BatchDecider()))
    assert r.status == "not_found" and r.profile is None


def test_one_failure_does_not_stop_run(seller):
    run = FakeRunner({"company": [LLMError("boom"), found("Hooli")], "people": [NOBODY] * 3})
    results = run_all([CompanyInput("A", None), CompanyInput("Hooli", None)], ctx(seller, run))
    assert [r.status for r in results] == ["failed", "done"]
    assert "boom" in results[0].reason


def test_done_company_carries_people_and_role_notes(seller):
    run = FakeRunner({"company": [found()], "people": [NOBODY] * 3})
    r = run_company(CompanyInput("Mercury Systems", None), ctx(seller, run))
    assert r.status == "done" and r.contacts == []
    assert r.role_notes == {role: "not found for this role" for role in seller.roles}


def test_failure_after_step0_keeps_profile(seller):
    run = FakeRunner({"company": [found()], "people": [LLMError("search down")]})
    r = run_company(CompanyInput("Mercury Systems", None), ctx(seller, run))
    assert r.status == "failed" and r.profile is not None and "search down" in r.reason


def person(name, role="champion", published="2026-05-01"):
    return Candidate(
        name=name, title="Head of Customer Service", company="Mercury Systems", buying_role=role, relevance=5,
        relevance_reason="r", why="w", sources=[Source(url=f"https://news.com/{name}", published=published)],
    )  # fmt: skip


def rc(name, still="yes"):
    return RoleCheck(name=name, still_there=still, current_title="Head of Customer Service",
                     departure_evidence="joined Initech in May 2026" if still == "no" else None)  # fmt: skip


def by_role(*cands):
    """Three per-role search answers, in seller role order."""
    return [PeopleAnswer(candidates=[c for c in cands if c.buying_role == r])
            for r in ("economic_buyer", "decision_maker", "champion")]  # fmt: skip


def test_step2_drops_leavers_and_parks_old(seller):
    people = by_role(person("Ann Berg", "economic_buyer"), person("Carl Dahl", "decision_maker"),
                     person("Eva Lind", "champion", published="2022-01-01"))  # fmt: skip
    checks = VerifyAnswer(checks=[rc("Ann Berg"), rc("Carl Dahl", "no"), rc("Eva Lind")])
    run = FakeRunner({"company": [found()], "people": people, "verify": [checks], "context": CTX, "drafts": DR, "why": WHY})
    r = run_company(CompanyInput("Mercury Systems", None), ctx(seller, run))
    assert [x.contact.name for x in r.contacts] == ["Ann Berg"] and r.contacts[0].contact.confidence == "high"
    assert [c.name for c in r.unconfirmed] == ["Eva Lind"]
    assert "Initech" in r.role_notes["decision_maker"] and "older than two years" in r.role_notes["champion"]


def test_dropped_pick_is_replaced_by_next_candidate(seller):
    people = by_role(person("Carl Dahl", "decision_maker"), person("Dana Holm", "decision_maker"))
    people[1].candidates[1].relevance = 4
    run = FakeRunner({"company": [found()], "people": people,
                      "verify": [VerifyAnswer(checks=[rc("Carl Dahl", "no")]), VerifyAnswer(checks=[rc("Dana Holm")])],
                      "context": CTX, "drafts": DR, "why": WHY})
    r = run_company(CompanyInput("Mercury Systems", None), ctx(seller, run))
    assert [x.contact.name for x in r.contacts] == ["Dana Holm"] and "decision_maker" not in r.role_notes
    assert len(run.prompts["verify"]) == 2


def test_pool_keeps_pick_across_runs_and_remembers_leavers(seller, tmp_path):
    store = CardStore(tmp_path, 0, TODAY)  # TTL 0 days: cards are fresh only today
    first = FakeRunner({"company": [found()], "people": by_role(person("Ann Berg"), person("Old Hand", "decision_maker")),
                        "verify": [VerifyAnswer(checks=[rc("Ann Berg"), rc("Old Hand", "no")])], "context": CTX, "drafts": DR, "why": WHY})  # fmt: skip
    run_company(CompanyInput("Mercury Systems", None), Ctx(seller, first, BatchDecider(), TODAY, store=store))
    later = CardStore(tmp_path, 0, date(2026, 11, 1))
    second = FakeRunner({"company": [found()], "people": by_role(person("Newer Face"), person("Old Hand", "decision_maker")),
                         "verify": [VerifyAnswer(checks=[rc("Ann Berg")])], "context": CTX, "drafts": DR, "why": WHY})  # fmt: skip
    r = run_company(CompanyInput("Mercury Systems", None), Ctx(seller, second, BatchDecider(), date(2026, 11, 1), store=later))
    assert [x.contact.name for x in r.contacts] == ["Ann Berg"]
    assert r.alternates["champion"][0].name == "Newer Face"
    assert "Ann Berg" in second.prompts["people"][2]
    assert "Old Hand" not in second.prompts["verify"][0]


def test_fresh_card_skips_verification(seller, tmp_path):
    store = CardStore(tmp_path, 14, TODAY)
    first = FakeRunner({"company": [found()], "people": by_role(person("Ann Berg")),
                        "verify": [VerifyAnswer(checks=[rc("Ann Berg")])], "context": CTX, "drafts": DR, "why": WHY})  # fmt: skip
    run_company(CompanyInput("Mercury Systems", None), Ctx(seller, first, BatchDecider(), TODAY, store=store))
    second = FakeRunner({"company": [found()], "people": by_role(person("Ann Berg")), "drafts": DR, "why": WHY})
    r = run_company(CompanyInput("Mercury Systems", None), Ctx(seller, second, BatchDecider(), TODAY, store=store))
    assert "verify" not in second.prompts and [x.contact.name for x in r.contacts] == ["Ann Berg"]


def test_colleagues_get_different_hooks(seller, monkeypatch):
    seen = []

    def fake_check(contact, context, profile, seller, run, used_hooks):
        seen.append(list(used_hooks))
        d = Drafts(linkedin_note="n", email_subject="s", email_body="b", hooks=[f"{contact.name} hook."])
        return d, CheckResult(mode="personal", basis="personal", attempts=1)

    monkeypatch.setattr(pipeline, "check_with_retry", fake_check)
    people = by_role(person("Ann Berg", "economic_buyer"), person("Carl Dahl", "decision_maker"))
    run = FakeRunner({"company": [found()], "people": people,
                      "verify": [VerifyAnswer(checks=[rc("Ann Berg"), rc("Carl Dahl")])], "context": CTX, "why": WHY})  # fmt: skip
    r = run_company(CompanyInput("Mercury Systems", None), ctx(seller, run))
    assert seen == [[], ["Ann Berg hook."]] and r.contacts[1].check.mode == "personal"


def test_every_contact_ends_with_drafts(seller):
    run = FakeRunner({"company": [found()], "people": by_role(person("Ann Berg")),
                      "verify": [VerifyAnswer(checks=[rc("Ann Berg")])], "context": CTX, "drafts": DR, "why": WHY})  # fmt: skip
    r = run_company(CompanyInput("Mercury Systems", None), ctx(seller, run))
    c = r.contacts[0]
    assert c.drafts.email_body.startswith("Hi Ann,") and c.check.mode == "template" and c.check.fixed


def test_parallel_run_keeps_input_order(seller):
    run = FakeRunner({"company": [CompanyAnswer(outcome="not_found")]})
    names = ["Alpha", "Beta", "Gamma", "Delta"]
    results = run_all([CompanyInput(n, None) for n in names], ctx(seller, run), workers=3)
    assert [r.input_name for r in results] == names


def test_why_is_rewritten_after_verification(seller):
    run = FakeRunner({"company": [found()], "people": by_role(person("Ann Berg")),
                      "verify": [VerifyAnswer(checks=[rc("Ann Berg")])], "context": CTX, "drafts": DR, "why": WHY})  # fmt: skip
    r = run_company(CompanyInput("Mercury Systems", None), ctx(seller, run))
    assert r.contacts[0].contact.why == "Owns the care budget."


def test_people_search_skipped_when_every_role_has_a_fresh_card(seller, tmp_path):
    store = CardStore(tmp_path, 14, TODAY)
    trio = by_role(person("Ann Berg", "economic_buyer"), person("Carl Dahl", "decision_maker"), person("Eva Lind", "champion"))
    first = FakeRunner({"company": [found()], "people": trio, "context": CTX, "drafts": DR, "why": WHY,
                        "verify": [VerifyAnswer(checks=[rc("Ann Berg"), rc("Carl Dahl"), rc("Eva Lind")])]})  # fmt: skip
    run_company(CompanyInput("Mercury Systems", None), Ctx(seller, first, BatchDecider(), TODAY, store=store))
    second = FakeRunner({"company": [found()], "drafts": DR, "why": WHY})  # no "people", no "verify": must not be called
    r = run_company(CompanyInput("Mercury Systems", None), Ctx(seller, second, BatchDecider(), TODAY, store=store))
    assert r.status == "done" and [x.contact.name for x in r.contacts] == ["Ann Berg", "Carl Dahl", "Eva Lind"]
