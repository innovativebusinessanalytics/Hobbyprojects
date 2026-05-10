#!/usr/bin/env python3
"""
Portfolio analyzer: pulls live holdings from Schwab and/or Fidelity,
enriches them with sector/geography/performance data, and prints a report.

Usage:
  cp .env.example .env       # fill in your credentials
  pip install -r requirements.txt
  python main.py             # fetches both brokers
  python main.py --schwab    # Schwab only
  python main.py --fidelity  # Fidelity only
  python main.py --no-enrich # skip yfinance enrichment

Errors are logged to portfolio.log in the same directory.
"""

import argparse
import sys
import os
import logging
import traceback
from dotenv import load_dotenv
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

load_dotenv()
console = Console()

logging.basicConfig(
    filename="portfolio.log",
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


def _require_env(*names):
    missing = [n for n in names if not os.getenv(n)]
    if missing:
        console.print(f"[red]Missing env vars: {', '.join(missing)}[/red]")
        console.print("Copy .env.example to .env and fill in your credentials.")
        sys.exit(1)
    return {n: os.environ[n] for n in names}


def fetch_schwab():
    from brokerage.schwab import SchwabClient
    env = _require_env("SCHWAB_APP_KEY", "SCHWAB_APP_SECRET")
    return SchwabClient(
        app_key=env["SCHWAB_APP_KEY"],
        app_secret=env["SCHWAB_APP_SECRET"],
        callback_url=os.getenv("SCHWAB_CALLBACK_URL", "https://127.0.0.1:8182"),
        token_path=os.getenv("SCHWAB_TOKEN_FILE", "schwab_token.json"),
    ).get_holdings()


def fetch_fidelity():
    from brokerage.fidelity import FidelityClient
    env = _require_env("FIDELITY_USERNAME", "FIDELITY_PASSWORD", "FIDELITY_ACCOUNT_IDS")
    account_ids = [a.strip() for a in env["FIDELITY_ACCOUNT_IDS"].split(",") if a.strip()]
    log.debug("Fetching Fidelity accounts: %s", account_ids)
    return FidelityClient(
        username=env["FIDELITY_USERNAME"],
        password=env["FIDELITY_PASSWORD"],
        account_ids=account_ids,
    ).get_holdings()


def fetch_fidelity_csv(path: str):
    from brokerage.fidelity import FidelityCSVClient
    return FidelityCSVClient(csv_path=path).get_holdings()


def main():
    parser = argparse.ArgumentParser(description="Portfolio analyzer")
    parser.add_argument("--schwab", action="store_true", help="Fetch Schwab holdings")
    parser.add_argument("--fidelity", action="store_true", help="Fetch Fidelity via OFX")
    parser.add_argument("--fidelity-csv", metavar="FILE", nargs="+", help="Load Fidelity holdings from one or more exported CSVs")
    parser.add_argument("--no-enrich", action="store_true", help="Skip yfinance enrichment")
    args = parser.parse_args()
    fetch_both = not args.schwab and not args.fidelity and not args.fidelity_csv

    fidelity_fn = (lambda: [h for f in args.fidelity_csv for h in fetch_fidelity_csv(f)]) if args.fidelity_csv else fetch_fidelity
    fidelity_flag = bool(args.fidelity or args.fidelity_csv or fetch_both)

    log.info("=== Run started ===")
    all_holdings = []
    with Progress(SpinnerColumn(), TextColumn("{task.description}"), transient=True) as progress:
        for name, fn, flag in [("Schwab", fetch_schwab, args.schwab or fetch_both),
                               ("Fidelity", fidelity_fn, fidelity_flag)]:
            if not flag:
                continue
            t = progress.add_task(f"Fetching {name}...")
            try:
                h = fn()
                all_holdings.extend(h)
                log.info("%s: fetched %d positions", name, len(h))
                progress.update(t, description=f"[green]{name}: {len(h)} positions[/green]")
            except Exception as e:
                log.error("%s fetch failed: %s\n%s", name, e, traceback.format_exc())
                console.print(f"[yellow]{name} failed:[/yellow] {e}")
                console.print("[dim]See portfolio.log for full details.[/dim]")
            progress.remove_task(t)

        if not all_holdings:
            console.print("[red]No holdings fetched. Check portfolio.log for details.[/red]")
            sys.exit(1)

        if not args.no_enrich:
            t = progress.add_task(f"Enriching {len(all_holdings)} positions...")
            from analysis.enrichment import enrich_holdings
            all_holdings = enrich_holdings(all_holdings)
            progress.remove_task(t)

    console.print(f"\n[bold green]Fetched {len(all_holdings)} total positions[/bold green]\n")
    from analysis.report import print_report
    print_report(all_holdings)
    log.info("=== Run complete ===")


if __name__ == "__main__":
    main()
