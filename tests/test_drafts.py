from conftest import FakeRunner
from prospect.models import CompanyProfile, Contact, ContactContext, Drafts, Fact, Source
from prospect.steps.drafts import grounding_failures, short_name, write_drafts

HOOK = "Guido Weissbrich said SuperTOBi solves 74% of customer queries on its own."
SIGNAL = "Vodafone plans to move from contact centres to proactive journeys."

CONTACT = Contact(
    name="Guido Weissbrich", title="Head of Customer Service", company="Vodafone", buying_role="champion",
    seniority="head", relevance=5, relevance_reason="r", why="Runs the service floor.",
    sources=[Source(url="https://teltarif.de/x")], confidence="high", linkedin_status="not_found", role_evidence="e",
)  # fmt: skip
CONTEXT = ContactContext(summary=[Fact(text=HOOK, source=Source(url="https://teltarif.de/x"))], personalization="personal")
PROFILE = CompanyProfile(
    input_name="Vodafone", resolved_name="Vodafone Group", domain="vodafone.com", fit="strong", fit_reason="r",
    signals=[Fact(text=SIGNAL, source=Source(url="https://vodafone.com/s1"))],
)  # fmt: skip


def drafts(hooks=(HOOK,), seller_facts=None, seller=None) -> Drafts:
    return Drafts(
        linkedin_note="Hi Guido", email_subject="SuperTOBi and your agents", email_body="Hi Guido",
        hooks=list(hooks), seller_facts=seller_facts if seller_facts is not None else [seller.facts[0].text],
    )  # fmt: skip


def test_grounded_drafts_pass(seller):
    assert grounding_failures(drafts(seller=seller), CONTEXT, PROFILE, seller) == []


def test_company_signal_counts_as_hook(seller):
    assert grounding_failures(drafts(hooks=[SIGNAL], seller=seller), CONTEXT, PROFILE, seller) == []


def test_unknown_hook_fails(seller):
    fails = grounding_failures(drafts(hooks=["Guido won an award."], seller=seller), CONTEXT, PROFILE, seller)
    assert len(fails) == 1 and "Guido won an award." in fails[0]


def test_unknown_seller_fact_fails(seller):
    fails = grounding_failures(drafts(seller_facts=["iX Hero cuts handle time by 40%."]), CONTEXT, PROFILE, seller)
    assert len(fails) == 1 and "40%" in fails[0]


def test_no_hook_fails(seller):
    assert grounding_failures(drafts(hooks=[], seller=seller), CONTEXT, PROFILE, seller)


def test_hook_match_ignores_case_and_spacing(seller):
    loose = "  guido weissbrich said SuperTOBi solves 74% of customer queries on its own "
    assert grounding_failures(drafts(hooks=[loose], seller=seller), CONTEXT, PROFILE, seller) == []


def test_prompt_has_everything_the_writer_needs(seller):
    run = FakeRunner({"drafts": [drafts(seller=seller)]})
    write_drafts(CONTACT, CONTEXT, PROFILE, seller, run, used_hooks=["Colleague hook."], feedback=["Note is 320 chars."])
    p = run.prompts["drafts"][0]
    for must in [f"P1. {HOOK}", f"P2. {SIGNAL}", "Guido", "Concentrix", seller.offers[0], f"S1. {seller.facts[0].text}", "Colleague hook.",
                 "Note is 320 chars.", "day-to-day", "270 characters", "150 words"]:  # fmt: skip
        assert must in p, must


def test_short_name_drops_legal_suffixes():
    assert short_name("Vodafone Group Plc") == "Vodafone" and short_name("Zalando SE") == "Zalando"
    assert short_name("ING Groep N.V.") == "ING Groep" and short_name("KLM") == "KLM" and short_name("Klarna Bank AB") == "Klarna Bank"


def test_pain_line_is_not_a_hook(seller):
    pain = Fact(text="Three in ten contacts, mostly complex, stay with agents.", source=Source(url="https://v.com", opened=True))
    ctx = CONTEXT.model_copy(update={"pain": pain})
    assert grounding_failures(drafts(hooks=[pain.text], seller=seller), ctx, PROFILE, seller)


def test_short_name_drops_brackets():
    assert short_name("IKEA (Inter IKEA Group franchisor; Ingka Group largest IKEA retailer)") == "IKEA"
    assert short_name("Klarna (Klarna Group plc)") == "Klarna"


def test_short_name_drops_part_of_tail():
    assert short_name("KLM Royal Dutch Airlines (Koninklijke Luchtvaart Maatschappij), part of Air France-KLM Group") == "KLM Royal Dutch Airlines"
