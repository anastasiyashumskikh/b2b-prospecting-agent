from datetime import date

from conftest import FakeRunner
from prospect.models import CompanyProfile, Contact, ContactContext, Fact, Source
from prospect.steps.context import gather_context

TODAY = date(2026, 10, 18)


def fact(text, published="2026-04-14", url="https://vodafone.com/news/a") -> Fact:
    return Fact(text=text, source=Source(url=url, published=published, opened=True))


CONTACT = Contact(
    name="Guido Weissbrich", title="Head of Customer Service", company="Vodafone", buying_role="champion",
    seniority="head", relevance=5, relevance_reason="r", why="w", sources=[Source(url="https://teltarif.de/x")],
    confidence="high", linkedin_status="not_found", role_evidence="e",
)  # fmt: skip

PROFILE = CompanyProfile(
    input_name="Vodafone", resolved_name="Vodafone Group", domain="vodafone.com", fit="strong", fit_reason="r",
    signals=[fact("Vodafone plans to move from contact centres to proactive journeys.", url="https://vodafone.com/s1"),
             fact("CFO said AI is delivering high standards in customer care.", url="https://vodafone.com/s2")],
)  # fmt: skip


def answer(*facts, personalization="personal", pain=None) -> ContactContext:
    return ContactContext(summary=list(facts), personalization=personalization, pain=pain)


def run_with(ctx: ContactContext) -> FakeRunner:
    return FakeRunner({"context": [ctx]})


def test_summary_capped_at_four(seller):
    facts = [fact(f"Weissbrich said thing {i}.", url=f"https://a.com/{i}") for i in range(5)]
    assert len(gather_context(CONTACT, PROFILE, seller, run_with(answer(*facts)), TODAY).summary) == 4


def test_short_summary_filled_with_company_signals(seller):
    ctx = gather_context(CONTACT, PROFILE, seller, run_with(answer(fact("Weissbrich spoke at CCW."))), TODAY)
    assert len(ctx.summary) == 2 and ctx.summary[1].source.url == "https://vodafone.com/s1"


def test_personal_needs_the_persons_name_in_a_fact(seller):
    ctx = gather_context(CONTACT, PROFILE, seller, run_with(answer(fact("Vodafone launched SuperTOBi."),
                                                                   fact("Care moved to WhatsApp."))), TODAY)  # fmt: skip
    assert ctx.personalization == "company"


def test_personal_kept_when_named(seller):
    ctx = gather_context(CONTACT, PROFILE, seller,
                         run_with(answer(fact("Weißbrich said SuperTOBi solves 74% of queries."),
                                         fact("Vodafone launched SuperTOBi."))), TODAY)  # fmt: skip
    assert ctx.personalization == "personal"


def test_no_facts_means_role_only(seller):
    empty_profile = PROFILE.model_copy(update={"signals": []})
    ctx = gather_context(CONTACT, empty_profile, seller, run_with(answer(personalization="personal")), TODAY)
    assert ctx.personalization == "role" and ctx.summary == []


def test_old_and_directory_facts_dropped(seller):
    facts = [fact("Weissbrich joined in 2019.", published="2019-05-01", url="https://a.com/old"),
             fact("Weissbrich profile.", url="https://rocketreach.co/guido"),
             fact("Weissbrich said SuperTOBi solves 74%.", url="https://teltarif.de/x"),
             fact("Weissbrich on CCW panel.", url="https://ccw.com/x")]  # fmt: skip
    ctx = gather_context(CONTACT, PROFILE, seller, run_with(answer(*facts)), TODAY)
    assert [f.source.url for f in ctx.summary] == ["https://teltarif.de/x", "https://ccw.com/x"]


def test_snippet_only_and_linkedin_facts_dropped(seller):
    snippet = Fact(text="Weissbrich posted about SuperTOBi.", source=Source(url="https://news.com/x", opened=False))
    linkedin = fact("Weissbrich post.", url="https://www.linkedin.com/posts/guido_x")
    ctx = gather_context(CONTACT, PROFILE, seller, run_with(answer(snippet, linkedin, fact("Weissbrich spoke at CCW."))), TODAY)
    assert [f.text for f in ctx.summary][0] == "Weissbrich spoke at CCW."


def test_prompt_carries_person_role_pain_and_signals(seller):
    run = run_with(answer(fact("Weissbrich spoke.")))
    gather_context(CONTACT, PROFILE, seller, run, TODAY)
    prompt = run.prompts["context"][0]
    assert "Guido Weissbrich" in prompt and "Head of Customer Service" in prompt and "2026-10-18" in prompt
    assert seller.roles["champion"].pain[:40] in prompt and "proactive journeys" in prompt
