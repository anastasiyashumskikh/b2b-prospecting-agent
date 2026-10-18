from datetime import date

from conftest import FakeRunner
from prospect.inputs import CompanyInput
from prospect.models import CompanyProfile, Fact, Source
from prospect.steps.company import CompanyAnswer, profile_company

TODAY = date(2026, 10, 18)


def signal(published: str | None, text: str = "Hiring 200 support agents") -> Fact:
    return Fact(text=text, source=Source(url="https://example.com/s", title="s", published=published, opened=True))


def profile(**kw) -> CompanyProfile:
    base = dict(input_name="x", resolved_name="Zalando SE", domain="zalando.com", fit="strong", fit_reason="r")
    return CompanyProfile(**(base | kw))


def test_old_and_undated_signals_dropped(seller):
    sigs = [signal("2026-09-01"), signal("2025-06-01", "old"), signal(None, "undated"), signal("2026-03")]
    run = FakeRunner({"company": [CompanyAnswer(outcome="found", profile=profile(signals=sigs))]})
    ans = profile_company(CompanyInput("Zalandoo", None), seller, run, TODAY)
    assert [s.source.published for s in ans.profile.signals] == ["2026-09-01", "2026-03"]


def test_at_most_three_signals_and_input_name_kept(seller):
    sigs = [signal(f"2026-0{i}-01", f"s{i}") for i in range(1, 6)]
    run = FakeRunner({"company": [CompanyAnswer(outcome="found", profile=profile(signals=sigs))]})
    ans = profile_company(CompanyInput("Zalandoo", None), seller, run, TODAY)
    assert len(ans.profile.signals) == 3 and ans.profile.input_name == "Zalandoo"


def test_prompt_carries_domain_icp_and_date(seller):
    run = FakeRunner({"company": [CompanyAnswer(outcome="found", profile=profile())]})
    profile_company(CompanyInput("Hooli", "hooli.com"), seller, run, TODAY)
    prompt = run.prompts["company"][0]
    assert "hooli.com" in prompt and "2026-10-18" in prompt and seller.icp[:40] in prompt


def test_snippet_only_signals_dropped(seller):
    seen_only = Fact(text="Hiring", source=Source(url="https://example.com/s", published="2026-09-01", opened=False))
    run = FakeRunner({"company": [CompanyAnswer(outcome="found", profile=profile(signals=[seen_only, signal("2026-09-02")]))]})
    ans = profile_company(CompanyInput("Zalando", None), seller, run, TODAY)
    assert [s.source.published for s in ans.profile.signals] == ["2026-09-02"]
