# B2B Prospecting Agent: write-up

Anastasiya Shumskikh, October 2026. Demo seller: Concentrix iX Suite (`seller.yaml`). Sample output: [5 companies, 15 contacts](../sample_output/demo/report.md). All 15 demo contacts were confirmed by hand on LinkedIn: they exist and hold the stated role now ([table](manual_contact_verification.md)).

## Q1. Architecture

- **A fixed pipeline.** Python runs the steps in order; the model works only inside a step.
  - 0 Company: resolve the name, rate ICP fit (strong / partial / weak), find 2–3 dated signals from the last 12 months.
  - 1 People: one search per buying role (economic buyer, decision-maker, champion), candidates rated 1–5 on how much they own what the seller sells. Code picks.
  - 2 Verify: one call per company checks each pick is still in the role; code sets confidence from source dates and domains. Then a one-line "why this person" is written from the verified facts only.
  - 3 Context: 2–4 sourced facts per person. 4 Drafts. 5 Checks. 6 Output: `report.md` and `results.json`.
- **The model:** Claude Code headless, `claude -p` with a JSON schema for the answer. Research steps get web search and page fetch only; the writer and the judge get no tools.
- **Why a fixed program and not a prompt-only agent.** In a prompt-only agent, step order, limits and format hold only while the model follows the text. In code they always hold, and each step is tested on its own (112 tests, no model calls).
- **Memory layer.** One card per contact, reused for 14 days. Per company, a candidate pool keeps everyone ever found and who was dropped and why; a picked person keeps the role until someone scores higher or leaves.
- **Autonomy boundary.** The agent prepares, the rep sends. An ambiguous name or weak fit is asked about in a manual run and parked under "Needs your decision" in a batch run.

## Q2. Data sources and integrations

- **Public web only:** conference speaker pages, trade media, newsrooms, press releases, job posts. Facts used in drafts come only from pages the agent opened; search snippets, LinkedIn pages and contact directories (RocketReach, ZoomInfo) never count as a source for them. A LinkedIn profile seen in search results may show that a person exists; it never supplies a fact for a draft.
- **Why not LinkedIn.** Its terms ban bots and scrapers, and the case asks for tools with suitable terms, so fetching linkedin.com is blocked in the tool settings. A profile URL from search is kept as evidence; shared connections read "not available without LinkedIn login". Production path: Sales Navigator through its partner program, the Sales Navigator Application Platform (approved partners only, CRM sync on Advanced Plus).
- **Alternatives considered:** Exa for people search; licensed people databases (People Data Labs, Apollo, ZoomInfo) for coverage, with a contract and their own GDPR terms; Clay-style enrichment, mainly for emails, which the case does not ask for. People search sits behind a `PeopleSource` interface, so any of these plugs in without touching the pipeline.
- **Why Claude Code in headless mode.** Web search, page reading and JSON-schema answers come built in, and every fact returns with its page URL, the main guard against invented people. It runs on a Claude subscription or an `ANTHROPIC_API_KEY`, so building and reviewing need no extra accounts.

## Q3. Limitations and failure modes

- **People search depends on the provider.** Claude Code's web search applies `site:linkedin.com/in` loosely and declines person-profile queries: on Zalando the first version found 1 person for 3 roles in 25 searches. I moved conference speakers, trade media and newsrooms ahead of LinkedIn results; Vodafone then gave 3 of 3 roles, all rated 5. Thin data ends in "not found for this role", never a guess. Production: a second people source.
- **Picks varied between runs,** since each search sees part of a company. Two runs of the Vodafone people search without cache picked different people in all 3 roles. Fix: candidate pool, sticky picks, one search per role with known names passed in, seniority as tie-break. After the fix, two fresh searches picked the same person in 2 of 3 roles. With the pool, a run keeps the people picked earlier unless someone scores higher, and when every role has a fresh card the agent does not search again.
- **Relevance scores move.** Two Vodafone candidates got 4 in one run and 5 in the other. Production: scores from structured title and department data, calibrated on a labelled set.
- **LinkedIn posts are unused,** so the freshest personal signal is often missing. Production: Sales Navigator data, or the rep pastes the profile and the agent rewrites the note.
- **No verified facts, generic draft.** Each draft is tagged by what it actually uses: personal, company news or general, so the rep sees which to rework. Demo: 8 of 15 drafts personal, 7 built on company news, 0 general.

## Q4. Scaling to 500 companies a day

**Cost, two ways to pay.** With a Claude subscription the company pays only for the subscription, and runs draw on its usage limits (set per 5-hour session and per week). The demo and all development, about 20 company runs and about 32M tokens, ran on one Claude Max 20x plan. With an API key, usage is billed per token: a company from scratch takes about 10 minutes and about 1.6M tokens (mostly cached input), about $2.40 at API list price, for 3 contacts. The final demo run reused the contact cards of earlier runs, so it took about a minute with no new searches. At production volume the agent runs on the API, so the per-token price is the one that matters here.

Today's baseline for 500 companies a day: about $1,200 and about 83 hours of sequential work. What changes:

- **API directly instead of Claude Code:** same steps and prompts, prompt caching, a search API, companies processed in parallel and in batches.
- **Refresh only what changed:** company signals daily, a person re-verified when a source shows a change, context only before outreach.
- **Cheaper models on narrow steps.** Every step runs on Opus today; verification and the judge move to a smaller model, checked against Opus on a sample.
- **A cost ceiling per company** (today cost is reported, not capped) and **a second people source**.
- **CRM:** `results.json` already holds the structured output; at scale it writes contacts and drafts to the CRM, and step 0 skips companies that are already the seller's clients (in the demo the agent found on its own that VodafoneThree already works with Concentrix).

## Q5. Three decisions for the engineering team

1. **Where people data comes from.** Recommendation: one licensed database as the main source, web search kept for context and evidence, Sales Navigator where the client has seats. Compare options on one fixed test list: roles filled, verified contacts, contract and GDPR terms.
2. **Where autonomy stops.** Recommendation: the agent prepares, the rep sends. Sending moves to the agent one segment at a time, after several weeks of few rep edits and zero fabricated claims in an audit sample, through the CRM's sequencing tool, which already handles opt-outs.
3. **How to keep fabricated facts at zero at scale.** Today the writer gets numbered facts and restates one per sentence. Code checks limits, banned phrases, names, that every hook is a listed fact and every number exists in one; a judge model checks each claim. A failing draft gets two rewrites, then a draft from seller facts only, then the seller-approved template, so every contact gets a sendable text. First try in the demo: 11 of 15. Recommendation: keep this contract, add an eval set of hand-checked companies, track fabricated claims as their own metric.

**Compliance.** Public professional data only: name, title, employer, sources; no emails or phones. For production: a GDPR legitimate-interest assessment, deletion of unused cards after a set period (today they are refreshed, not deleted), an opt-out list checked at step 0, a process for erasure requests.
