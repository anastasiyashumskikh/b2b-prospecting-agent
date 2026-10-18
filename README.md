# B2B Prospecting Agent

Give it a list of companies. For each one it finds up to three people from the buying group (economic buyer, decision-maker, champion), checks they still hold the role, collects public context on each, and drafts a LinkedIn connection note (up to 300 characters) and a cold email (up to 150 words). Every person and every fact carries a public source. The agent prepares; a sales rep reviews and sends. The demo seller is Concentrix iX Suite.

## Start here

- **Sample output:** [5 companies, 15 contacts with notes and emails](sample_output/demo/report.md)
- **Write-up, Q1–Q5:** [docs/writeup_Q1-Q5.md](docs/writeup_Q1-Q5.md)
- **Hard inputs:** [ambiguous name, typo, small company, non-English company, competitor](sample_output/edge_cases/report.md), summary [below](#behavior-at-the-edges)
- **Manual check:** [all 15 demo contacts confirmed by hand on LinkedIn](docs/manual_contact_verification.md): they exist and hold the stated role now

**Cost.** With a Claude subscription you pay only for the subscription: runs draw on its usage limits. The demo and all development, about 20 company runs, ran on one Claude Max 20x plan. With an `ANTHROPIC_API_KEY` usage is billed per token: one company from scratch takes about 10 minutes and about 1.6M tokens, about $2.40 at API list price.

## Setup

Needs Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```
uv sync
```

The agent runs on Claude Code. Install it ([setup guide](https://docs.claude.com/en/docs/claude-code/setup)) and either log in once with a Claude account (the run uses that subscription) or set `ANTHROPIC_API_KEY` (calls are billed to that key). Before a run the agent checks that Claude Code answers and says what is missing if it does not.

## Run

```
uv run prospect "Vodafone" "Lufthansa"
uv run prospect "Mercury | mercury.com"          # pin the domain
uv run prospect --file examples/demo_companies.txt --batch
uv run prospect --file examples/edge_case_companies.txt --batch
```

| Option | What it does |
|---|---|
| `--file PATH` | One company per line, `Name` or `Name \| domain.com`; `#` starts a comment |
| `--batch` | Never asks. Ambiguous names and weak-fit companies go to "Needs your decision" with the reason. Also the default when there is no terminal |
| `--workers N` | Companies processed at once in `--batch`, default 3 |
| `--seller PATH` | Seller description, default `seller.yaml` |
| `--card-ttl-days N` | Reuse contact cards younger than N days, default 14 |

Without `--batch` the agent asks in the terminal when a name fits several companies or a company looks like a weak fit.

## Output

Each run writes `runs/<date-time>/` (the sample output in `sample_output/` was produced this way):

- `report.md`, readable on GitHub: a run summary and a table of all contacts, then per company the fit and signals with sources, and per contact the title, buying role and why, confidence and sources, context, LinkedIn note and email with counters, and what the drafts rest on (personal / company news / general).
- `results.json`: the same data, structured for a CRM import.

Two folders stay local and are not committed: `cards/` (one card per contact plus a candidate pool per company, the memory between runs) and `.cache/` (model answers, so an identical call is not paid twice).

## Behavior at the edges

Inputs that should not be easy, run through the same agent (`examples/edge_case_companies.txt`, report in [sample_output/edge_cases/report.md](sample_output/edge_cases/report.md)):

| Input | What the agent did |
|---|---|
| Mercury | Ambiguous name: parked under "Needs your decision" with six candidate companies and their domains. In a manual run it asks which one. |
| Klarnaa | Typo: resolved to Klarna and shows "Klarnaa → Klarna"; contacts and drafts as usual. |
| Holded | Small company (about 100–150 people): weak fit, parked with the reason. |
| Teleperformance | Direct competitor of Concentrix: weak fit, parked with the reason. |
| Mercadona | Few English sources: worked from Spanish-language press, partial fit, two contacts; the third role honestly "not found". |
| Zalando | Little public data on support leaders: one contact; the other roles show "only weak matches" or "not found", never a guess. |

## Point it at another seller

Copy `seller.yaml`, edit it, and run with `--seller my_seller.yaml`. The file holds:

- `name`, `company`, `summary`, `icp`: what is sold and to whom; `icp` drives the fit rating.
- `facts`: what the drafts may say about the seller, each with a source URL. The agent claims nothing else.
- `offers`: the only next steps a draft may propose (for example, a 20-minute demo).
- `fallback`: the last-resort note and email, used only if every written draft fails the checks. Build it from `facts` only; `{first_name}` and `{company}` are filled in.
- `roles`: titles, pain and search hints for each buying role.

## Tests

```
uv run pytest            # no model calls
uv run pytest -m live    # one real call to the claude CLI
```

## What is in the repo

| Path | What it is |
|---|---|
| `src/prospect/pipeline.py` | Runs the steps in a fixed order for each company; in `--batch` several companies run in parallel |
| `src/prospect/steps/` | One module per step: company, people, verify, why, context, drafts, checks |
| `src/prospect/llm.py` | Calls Claude Code in headless mode (`claude -p`, JSON-schema answers) |
| `src/prospect/report.py` | Writes `report.md` and `results.json` |
| `seller.yaml` | The seller: product facts with sources, ideal customer profile, buying roles, offers, fallback template |
| `examples/` | Demo company list and hard inputs with the expected behavior |
| `sample_output/` | The sample output: `demo/` (5 companies) and `edge_cases/` (hard inputs), each with `report.md` and `results.json` |
| `docs/` | Write-up with the answers to Q1–Q5, manual verification of the demo contacts |
| `tests/` | 112 tests for what the code decides: limits, banned phrases, merging people, picks, confidence, parsing model answers |

## What it does not do

- Send anything. Every draft waits for a rep.
- Find emails or phone numbers.
- Log into LinkedIn or open its pages. A LinkedIn profile seen in search results is kept as evidence that the person exists; facts in drafts come only from pages the agent opened.
- Offer a web interface. It runs from the command line.
