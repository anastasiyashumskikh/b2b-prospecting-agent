"""Command line entry point: `uv run prospect "Company A" "Company B"` or `uv run prospect --file companies.txt`."""

import argparse
import sys
import time
from datetime import date, datetime
from pathlib import Path

from prospect.cards import CardStore
from prospect.config import CARD_TTL_DAYS
from prospect.inputs import parse_input
from prospect.llm import ClaudeRunner, preflight
from prospect.pipeline import BatchDecider, Ctx, InteractiveDecider, run_all
from prospect.report import summarize, write_run
from prospect.seller import load_seller


def main() -> None:
    ap = argparse.ArgumentParser(prog="prospect", description=__doc__)
    ap.add_argument("companies", nargs="*", help='Company names; "Name | domain.com" to pin the domain')
    ap.add_argument("--file", type=Path, help="One company per line, same format")
    ap.add_argument("--batch", action="store_true", help="Never ask: park unclear companies for your decision")
    ap.add_argument("--seller", type=Path, default=Path("seller.yaml"), help="Seller description (default: seller.yaml)")
    ap.add_argument("--workers", type=int, default=3, help="Companies processed at once in --batch mode (default 3)")
    ap.add_argument("--card-ttl-days", type=int, default=CARD_TTL_DAYS, help="Reuse contact cards younger than this")
    args = ap.parse_args()

    companies = parse_input(args.companies, args.file)
    if not companies:
        ap.error("give at least one company name or --file")
    seller = load_seller(args.seller)
    preflight()
    run = ClaudeRunner(Path(".cache"))
    batch = args.batch or not sys.stdin.isatty()
    today = date.today()
    decider = BatchDecider() if batch else InteractiveDecider()
    ctx = Ctx(seller, run, decider, today, store=CardStore(Path("cards"), args.card_ttl_days, today))
    started, t0 = datetime.now(), time.monotonic()
    results = run_all(companies, ctx, workers=args.workers if batch else 1)  # questions need one company at a time
    summary = summarize(results, time.monotonic() - t0, run.total_cost_usd, run.total_searches)
    run_dir = Path("runs") / started.strftime("%Y-%m-%d_%H%M")
    write_run(results, summary, run_dir, started.strftime("%Y-%m-%d %H:%M"), seller.name)
    print(f"\nReport: {run_dir / 'report.md'}  ({summary.duration_s / 60:.0f} min, {summary.searches} searches)")
