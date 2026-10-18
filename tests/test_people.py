from conftest import FakeRunner
from prospect.models import Candidate, CompanyProfile, Fact, Source
from prospect.steps.verify import person_key
from prospect.steps.people import PeopleAnswer, WebSearchPeopleSource, pick_per_role


def cand(name, role="economic_buyer", relevance=5, n_sources=1, published="2026-05-01", seniority="vp") -> Candidate:
    sources = [Source(url=f"https://e.com/{name}/{i}", published=published) for i in range(n_sources)]
    return Candidate(
        name=name, title="VP Customer Care", company="Zalando SE", buying_role=role, seniority=seniority,
        relevance=relevance, relevance_reason="r", why="w", sources=sources,
    )  # fmt: skip


def names(picks):
    return [c.name for c in picks.chosen]


def test_relevance_beats_seniority_and_sources():
    picks = pick_per_role([cand("Many Links", relevance=4, n_sources=5, seniority="c_level"), cand("Best Fit")])
    assert names(picks) == ["Best Fit"]


def test_seniority_breaks_relevance_tie():
    picks = pick_per_role([cand("Manager", seniority="manager", n_sources=3), cand("Director", seniority="director")])
    assert names(picks) == ["Director"]
    assert "less senior" in picks.alternates["economic_buyer"][0].why_not


def test_director_and_head_are_one_tier():
    picks = pick_per_role([cand("Head", seniority="head", n_sources=2), cand("Director", seniority="director")])
    assert names(picks) == ["Head"]


def test_sources_then_freshness_break_ties():
    assert names(pick_per_role([cand("Old", published="2024-01-01"), cand("New", published="2026-09-01")])) == ["New"]
    assert names(pick_per_role([cand("One"), cand("Two", n_sources=2)])) == ["Two"]


def test_one_per_role_max_three():
    roles = ["economic_buyer", "decision_maker", "champion"] * 2
    cands = [cand(n, r) for n, r in zip(["Ann Berg", "Carl Dahl", "Eva Lind", "Dana Holm", "Ivo Kask", "Lea Moor"], roles)]
    picks = pick_per_role(cands)
    assert len(picks.chosen) == 3 and picks.notes == {}
    assert {c.buying_role for c in picks.chosen} == {"economic_buyer", "decision_maker", "champion"}


def test_weak_matches_leave_role_empty_with_names():
    picks = pick_per_role([cand("Weak One", "champion", relevance=2)])
    assert picks.chosen == []
    assert "only weak matches found" in picks.notes["champion"] and "Weak One" in picks.notes["champion"]
    assert picks.notes["economic_buyer"] == "not found for this role"


def test_candidate_without_sources_dropped():
    assert pick_per_role([cand("Ghost", n_sources=0)]).chosen == []


def test_same_person_takes_one_role_only():
    cands = [cand("Jane Doe"), cand("jane doe", "decision_maker"), cand("Ann Lee", "decision_maker", 4)]
    picks = pick_per_role(cands)
    assert [(c.name, c.buying_role) for c in picks.chosen] == [("Jane Doe", "economic_buyer"), ("Ann Lee", "decision_maker")]


def test_incumbent_keeps_role_against_equal_newcomer():
    cands = [cand("Newcomer", n_sources=3, seniority="c_level"), cand("Incumbent", seniority="director")]
    picks = pick_per_role(cands, incumbents={"economic_buyer": person_key("Incumbent")})
    assert names(picks) == ["Incumbent"]
    assert picks.alternates["economic_buyer"][0].name == "Newcomer"


def test_incumbent_replaced_by_higher_relevance():
    picks = pick_per_role([cand("Better"), cand("Incumbent", relevance=4)], incumbents={"economic_buyer": person_key("Incumbent")})
    assert names(picks) == ["Better"]


def test_excluded_people_are_skipped():
    assert names(pick_per_role([cand("Left Co"), cand("Stayed", relevance=4)], excluded={"l-co"})) == ["Stayed"]


def test_at_most_two_alternates_and_they_are_eligible():
    cands = [cand("A One"), cand("B Two", relevance=4), cand("C Three", relevance=4), cand("D Four", relevance=3),
             cand("E Weak", relevance=2)]  # fmt: skip
    alts = pick_per_role(cands).alternates["economic_buyer"]
    assert [a.name for a in alts] == ["B Two", "C Three"] and "relevance 4 vs 5" in alts[0].why_not


def profile():
    return CompanyProfile(
        input_name="Zalando", resolved_name="Zalando SE", domain="zalando.com", fit="strong", fit_reason="r",
        signals=[Fact(text="Customer care is outsourced to TP", source=Source(url="https://e.com"))],
    )  # fmt: skip


def test_one_search_per_role_with_hints_and_signals(seller):
    run = FakeRunner({"people": [PeopleAnswer(candidates=[])] * 3})
    WebSearchPeopleSource(run).find(profile(), seller, [])
    prompts = run.prompts["people"]
    assert len(prompts) == 3
    for prompt, (role, spec) in zip(prompts, seller.roles.items()):
        assert "Customer care is outsourced to TP" in prompt and "zalando.com" in prompt
        assert f'buying_role: "{role}"' in prompt and spec.titles[0] in prompt and all(h in prompt for h in spec.hints)


def test_found_people_get_the_searched_role_and_known_names_are_passed(seller):
    wrong_role = cand("Ann Berg", "champion")
    run = FakeRunner({"people": [PeopleAnswer(candidates=[wrong_role]), PeopleAnswer(candidates=[]),
                                 PeopleAnswer(candidates=[])]})  # fmt: skip
    found = WebSearchPeopleSource(run).find(profile(), seller, [cand("Known Person", "decision_maker")])
    assert found[0].buying_role == "economic_buyer"
    assert "Known Person" in run.prompts["people"][1] and "Known Person" not in run.prompts["people"][0]
