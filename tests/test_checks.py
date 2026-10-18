from conftest import FakeRunner
from prospect.models import CompanyProfile, Contact, ContactContext, Drafts, Fact, Source
from prospect.steps.checks import JudgeVerdict, check_with_retry, rule_failures, template_drafts

HOOK = "Guido Weissbrich said SuperTOBi solves 74% of customer queries on its own."
CONTACT = Contact(
    name="Guido Weissbrich", title="Head of Customer Service", company="Vodafone", buying_role="champion",
    seniority="head", relevance=5, relevance_reason="r", why="w", sources=[Source(url="https://teltarif.de/x")],
    confidence="high", linkedin_status="not_found", role_evidence="e",
)  # fmt: skip
CONTEXT = ContactContext(summary=[Fact(text=HOOK, source=Source(url="https://teltarif.de/x"))], personalization="personal")
PROFILE = CompanyProfile(input_name="Vodafone", resolved_name="Vodafone", domain="vodafone.com", fit="strong", fit_reason="r")

NOTE = "Hi Guido, I'm [name] from Concentrix. Saw that SuperTOBi now solves 74% of queries on its own."
BODY = "Hi Guido,\n\nSuperTOBi now solves 74% of queries. Happy to show you a 20-minute demo.\n\nBest,\n[Your name]"


def good(seller, **kw) -> Drafts:
    base = dict(linkedin_note=NOTE, email_subject="SuperTOBi and your agents", email_body=BODY, hooks=[HOOK],
                seller_facts=[seller.facts[0].text])  # fmt: skip
    return Drafts(**(base | kw))


OK = JudgeVerdict(specific=True, specific_reason="names SuperTOBi result")


def rules(d, seller):
    return rule_failures(d, CONTACT, CONTEXT, PROFILE, seller)


def test_good_drafts_pass_rules(seller):
    assert rules(good(seller), seller) == []


def test_limits_at_and_over(seller):
    assert rules(good(seller, linkedin_note=("Guido " + "x" * 294)[:300]), seller) == []
    assert any("301 characters" in f for f in rules(good(seller, linkedin_note="Guido " + "x" * 295), seller))
    with_name = "Guido [Your name] " + "x" * 270  # 288 as written, 299 with a 22-character name
    assert rules(good(seller, linkedin_note=with_name), seller) == []
    assert any("characters with a real sender name" in f for f in rules(good(seller, linkedin_note=with_name + "xx"), seller))
    assert any("151 words" in f for f in rules(good(seller, email_body="Guido " + "word " * 150), seller))
    assert any("subject is 7 words" in f for f in rules(good(seller, email_subject="a b c d e f g"), seller))


def test_banned_phrase_dash_and_exclamation(seller):
    f = rules(good(seller, email_body=BODY + " I Hope This Finds You Well — great!"), seller)
    assert any("i hope this finds you well" in x for x in f)
    assert "long dash character used" in f and "exclamation mark or ellipsis used" in f


def test_numbers_must_come_from_facts(seller):
    assert rules(good(seller, email_body=BODY + " We closed nearly 100 iX deals; TMC 2026."), seller) == []
    f = rules(good(seller, email_body=BODY + " Handle time drops 3x."), seller)
    assert f == ["numbers not found in any fact: 3"]


def test_first_name_required(seller):
    assert any("first name" in f for f in rules(good(seller, linkedin_note="Hi there, I'm [name]."), seller))


def test_fallback_template_passes_rules_for_any_company(seller):
    for company in ["Vodafone", "KLM", "ING"]:
        d = template_drafts(CONTACT, PROFILE.model_copy(update={"resolved_name": company}), seller)
        assert rules(d, seller) == [] and company in d.email_body and "{" not in d.email_body


def test_first_attempt_passes(seller):
    run = FakeRunner({"drafts": [good(seller)], "judge": [OK]})
    d, c = check_with_retry(CONTACT, CONTEXT, PROFILE, seller, run)
    assert c.mode == "personal" and c.basis == "personal" and c.attempts == 1 and c.fixed == []


def test_rewrite_gets_exact_problems(seller):
    bad = JudgeVerdict(specific=True, specific_reason="r", unsupported_claims=["'in every market' is not in the fact"])
    run = FakeRunner({"drafts": [good(seller), good(seller)], "judge": [bad, OK]})
    d, c = check_with_retry(CONTACT, CONTEXT, PROFILE, seller, run)
    assert c.mode == "personal" and c.attempts == 2 and "in every market" in run.prompts["drafts"][1]
    assert any("in every market" in f for f in c.fixed)


def test_rule_failure_skips_judge(seller):
    run = FakeRunner({"drafts": [good(seller, email_body=BODY + " 3x"), good(seller)], "judge": [OK]})
    check_with_retry(CONTACT, CONTEXT, PROFILE, seller, run)
    assert len(run.prompts["judge"]) == 1


def test_safe_draft_after_three_failures(seller):
    invented = JudgeVerdict(specific=True, specific_reason="r", invented_sender_actions=["watched your talk"])
    safe = good(seller, hooks=[], linkedin_note="Hi Guido, I'm [name] from Concentrix.")
    run = FakeRunner({"drafts": [good(seller)] * 3 + [safe], "judge": [invented] * 3 + [OK]})
    d, c = check_with_retry(CONTACT, CONTEXT, PROFILE, seller, run)
    assert c.mode == "safe" and c.basis == "role" and c.attempts == 4 and d.hooks == []
    assert "Return hooks as an empty list" in run.prompts["drafts"][3]


def test_rewrites_carry_every_earlier_problem(seller):
    first = JudgeVerdict(specific=True, specific_reason="r", invented_sender_actions=["watched your talk"])
    second = JudgeVerdict(specific=True, specific_reason="r", unsupported_claims=["in every market"])
    run = FakeRunner({"drafts": [good(seller)] * 3, "judge": [first, second, OK]})
    check_with_retry(CONTACT, CONTEXT, PROFILE, seller, run)
    assert "watched your talk" in run.prompts["drafts"][2] and "in every market" in run.prompts["drafts"][2]


def test_generic_is_fine_only_for_safe_drafts(seller):
    generic = JudgeVerdict(specific=False, specific_reason="could go to anyone")
    safe = good(seller, hooks=[])
    run = FakeRunner({"drafts": [good(seller)] * 3 + [safe], "judge": [generic]})
    d, c = check_with_retry(CONTACT, CONTEXT, PROFILE, seller, run)
    assert c.mode == "safe"


def test_template_when_everything_fails(seller):
    run = FakeRunner({"drafts": [good(seller, email_body="no name, 3x")]})
    d, c = check_with_retry(CONTACT, CONTEXT, PROFILE, seller, run)
    assert c.mode == "template" and c.basis == "role" and d.email_body.startswith("Hi Guido,")
    assert rules(d, seller) == [] and "judge" not in run.prompts


def test_sender_actions_are_banned_by_rules(seller):
    f = rules(good(seller, email_body=BODY + " I watched your talk and I saw the results."), seller)
    assert any("i watched" in x for x in f) and any("i saw" in x for x in f)


def test_basis_follows_the_hooks_actually_used(seller):
    from prospect.steps.checks import drafts_basis
    assert drafts_basis(good(seller), CONTACT) == "personal"
    assert drafts_basis(good(seller, hooks=["Vodafone launched SuperTOBi."]), CONTACT) == "company"
    assert drafts_basis(good(seller, hooks=[]), CONTACT) == "role"


def test_stock_praise_is_banned(seller):
    assert any("nice result" in f for f in rules(good(seller, email_body=BODY + " Nice result."), seller))
