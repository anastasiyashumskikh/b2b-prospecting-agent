from datetime import date

from conftest import FakeRunner
from prospect.models import Candidate, CompanyProfile, Source
from prospect.steps.verify import (
    first_name,
    RoleCheck,
    VerifyAnswer,
    assess,
    check_linkedin,
    merge_candidates,
    person_key,
    verify_people,
)

TODAY = date(2026, 10, 18)


def src(url="https://vodafone.com/news/a", published="2026-04-14", title="") -> Source:
    return Source(url=url, published=published, title=title)


def cand(name="Guido Weissbrich", title="Head of Customer Service", sources=None, linkedin=None) -> Candidate:
    return Candidate(
        name=name, title=title, company="Vodafone", buying_role="champion", relevance=5,
        relevance_reason="r", why="w", linkedin_url=linkedin, sources=sources if sources is not None else [src()],
    )  # fmt: skip


def check(name="Guido Weissbrich", still="yes", evidence=None, li_confirmed=False, title_ok=True) -> RoleCheck:
    return RoleCheck(
        name=name, still_there=still, current_title="Head of Customer Service", title_confirmed=title_ok,
        evidence=evidence or [], departure_evidence=None, linkedin_confirmed=li_confirmed,
    )  # fmt: skip


def test_merge_accents_and_initials():
    merged = merge_candidates([
        cand("José Müller", sources=[src("https://a.com/1")]),
        cand("Jose Muller", sources=[src("https://b.com/2")]),
        cand("Jane A. Doe", sources=[src("https://c.com/3")]),
        cand("jane doe", sources=[src("https://c.com/3")]),
    ])  # fmt: skip
    assert len(merged) == 2
    assert {len(c.sources) for c in merged} == {2, 1}


def test_person_key_is_ascii_and_stable():
    assert person_key("José A. Müller") == person_key("jose muller") == "j-muller"


def test_person_key_ignores_nicknames_and_short_forms():
    assert person_key("Beverley (Bev) Bartlett") == person_key("Bev (Beverley) Bartlett") == person_key("Bev Bartlett")
    assert person_key("Tom Smith") == person_key("Thomas Smith")
    assert person_key("Ann Berg") != person_key("Carl Berg")


def test_left_company_excluded():
    assert assess(cand(), check(still="no"), TODAY) is None


def test_former_in_title_excluded():
    assert assess(cand(title="Former VP Customer Care"), check(), TODAY) is None


def test_two_domains_high():
    c = cand(sources=[src("https://a.com/x", None), src("https://www.b.com/y", None)])
    assert assess(c, check(), TODAY).confidence == "high"


def test_fresh_dated_high():
    assert assess(cand(sources=[src(published="2026-04-14")]), check(), TODAY).confidence == "high"


def test_single_undated_medium():
    assert assess(cand(sources=[src(published=None)]), check(), TODAY).confidence == "medium"


def test_only_old_sources_low():
    c = cand(sources=[src("https://a.com/x", "2023-01-01"), src("https://b.com/y", "2024-02-01")])
    assert assess(c, check(), TODAY).confidence == "low"


def test_unclear_check_capped_at_medium():
    assert assess(cand(), check(still="unclear"), TODAY).confidence == "medium"


def test_future_event_date_counts_as_fresh():
    assert assess(cand(sources=[src(published="2026-11-26")]), check(), TODAY).confidence == "high"


def test_directory_sites_are_not_sources():
    c = cand(sources=[src("https://rocketreach.co/guido", "2026-09-01")])
    assert assess(c, check(), TODAY) is None


def test_verification_evidence_is_merged_in():
    c = cand(sources=[src(published=None)])
    contact = assess(c, check(evidence=[src("https://teltarif.de/x", "2026-04-27")]), TODAY)
    assert contact.confidence == "high" and len(contact.sources) == 2


def test_non_profile_linkedin_url_is_not_found():
    for url in [
        "https://www.linkedin.com/posts/guido-weissbrich_abc",
        "https://www.linkedin.com/company/vodafone/",
        "https://www.linkedin.com/pulse/some-article",
        "https://example.com/in/guido-weissbrich",
        None,
    ]:
        assert check_linkedin(url, "Guido Weissbrich", confirmed=False) == "not_found", url


def test_profile_matches_only_when_confirmed():
    assert check_linkedin("https://de.linkedin.com/in/guido-weissbrich-12", "Guido Weissbrich", True) == "matched"
    assert check_linkedin("https://www.linkedin.com/in/lilly-ebert/", "Lilly Ebert", False) == "not_found"


def test_one_verify_call_for_all_people():
    profile = CompanyProfile(input_name="Vodafone", resolved_name="Vodafone Group", domain="vodafone.com",
                             fit="strong", fit_reason="r")  # fmt: skip
    run = FakeRunner({"verify": [VerifyAnswer(checks=[check("Ann Berg"), check("Carl Dahl")])]})
    checks = verify_people([cand("Ann Berg"), cand("Carl Dahl")], profile, run, TODAY)
    assert len(run.prompts["verify"]) == 1 and set(checks) == {"a-berg", "c-dahl"}
    assert "Ann Berg" in run.prompts["verify"][0] and "2026-10-18" in run.prompts["verify"][0]


def test_title_doubt_caps_at_medium_and_uses_newer_title():
    newer = check(title_ok=False).model_copy(update={"current_title": "Consumer Operations Director"})
    contact = assess(cand(), newer, TODAY)
    assert contact.confidence == "medium" and contact.title == "Consumer Operations Director"


def test_person_key_ignores_honorifics():
    assert person_key("Dr Tania Caporaso") == person_key("Tania Caporaso") == "t-caporaso"
    assert person_key("Dr. Christian Niedworok") == "c-niedworok"


def test_first_name_skips_honorifics():
    assert first_name("Dr. Christian Niedworok") == "Christian" and first_name("Dr Tania Caporaso") == "Tania"
    assert first_name("Bev (Beverley) Bartlett") == "Bev" and first_name("José Müller") == "José"
