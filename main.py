#!/usr/bin/env python3
"""
Portfolio analyzer: pulls live holdings from Fidelity,
enriches them with sector/geography/performance data, and prints a report.

Usage:
  cp .env.example .env       # fill in your credentials
  pip install -r requirements.txt
  python main.py             # fetch holdings
  python main.py --no-enrich # skip yfinance enrichment
"""

import argparse
import sys
import os
from dotenv import load_dotenv
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

load_dotenv()
console = Console()


def _require_env(*names):
    missing = [n for n in names if not os.getenv(n)]
    if missing:
        console.print(f"[red]Missing env vars: {', '.join(missing)}[/red]")
        console.print("Copy .env.example to .env and fill in your credentials.")
        sys.exit(1)
    return {n: os.environ[n] for n in names}


def fetch_fidelity():
    from brokerage.fidelity import FidelityClient
    env = _require_env("FIDELITY_USERNAME", "FIDELITY_PASSWORD", "FIDELITY_ACCOUNT_IDS")
    account_ids = [a.strip() for a in env["FIDELITY_ACCOUNT_IDS"].split(",") if a.strip()]
    return FidelityClient(
        username=env["FIDELITY_USERNAME"],
        password=env["FIDELITY_PASSWORD"],
        account_ids=account_ids,
    ).get_holdings()


def main():
    parser = argparse.ArgumentParser(description="Portfolio analyzer")
    parser.add_argument("--no-enrich", action="store_true", help="Skip yfinance enrichment")
    args = parser.parse_args()

    all_holdings = []

    with Progress(SpinnerColumn(), TextColumn("{task.description}"), transient=True) as progress:
        t = progress.add_task("Fetching Fidelity holdings...")
        try:
            holdings = fetch_fidelity()
            all_holdings.extend(holdings)
            progress.update(t, description=f"[green]Fidelity: {len(holdings)} positions[/green]")
        except Exception as e:
            console.print(f"[yellow]Fidelity fetch failed:[/yellow] {e}")
        progress.remove_task(t)

        if not all_holdings:
            console.print("[red]No holdings fetched. Check your credentials and account IDs.[/red]")
            sys.exit(1)

        if not args.no_enrich:
            t = progress.add_task(f"Enriching {len(all_holdings)} positions...")
            from analysis.enrichment import enrich_holdings
            all_holdings = enrich_holdings(all_holdings)
            progress.remove_task(t)

    console.print(f"\n[bold green]Fetched {len(all_holdings)} total positions[/bold green]\n")
    from analysis.report import print_report
    print_report(all_holdings)


if __name__ == "__main__":
    main()
