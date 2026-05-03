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
"""

import argparse
import sys
import os
from dotenv import load_dotenv
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

load_dotenv()
console = Console()


def _require_env(*names: str) -> dict[str, str]:
    missing = [n for n in names if not os.getenv(n)]
    if missing:
        console.print(f"[red]Missing env vars: {', '.join(missing)}[/red]")
        console.print("Copy .env.example to .env and fill in your credentials.")
        sys.exit(1)
    return {n: os.environ[n] for n in names}


def fetch_schwab() -> list:
    from brokerage.schwab import SchwabClient
    env = _require_env("SCHWAB_APP_KEY", "SCHWAB_APP_SECRET")
    client = SchwabClient(
        app_key=env["SCHWAB_APP_KEY"],
        app_secret=env["SCHWAB_APP_SECRET"],
        callback_url=os.getenv("SCHWAB_CALLBACK_URL", "https://127.0.0.1:8182"),
        token_path=os.getenv("SCHWAB_TOKEN_FILE", "schwab_token.json"),
    )
    return client.get_holdings()


def fetch_fidelity() -> list:
    from brokerage.fidelity import FidelityClient
    env = _require_env("FIDELITY_USERNAME", "FIDELITY_PASSWORD", "FIDELITY_ACCOUNT_IDS")
    account_ids = [a.strip() for a in env["FIDELITY_ACCOUNT_IDS"].split(",") if a.strip()]
    client = FidelityClient(
        username=env["FIDELITY_USERNAME"],
        password=env["FIDELITY_PASSWORD"],
        account_ids=account_ids,
    )
    return client.get_holdings()


def main() -> None:
    parser = argparse.ArgumentParser(description="Portfolio analyzer")
    parser.add_argument("--schwab", action="store_true", help="Fetch Schwab holdings only")
    parser.add_argument("--fidelity", action="store_true", help="Fetch Fidelity holdings only")
    parser.add_argument("--no-enrich", action="store_true", help="Skip yfinance enrichment")
    args = parser.parse_args()

    fetch_both = not args.schwab and not args.fidelity

    all_holdings = []

    with Progress(SpinnerColumn(), TextColumn("{task.description}"), transient=True) as progress:
        if args.schwab or fetch_both:
            task = progress.add_task("Fetching Schwab holdings...")
            try:
                holdings = fetch_schwab()
                all_holdings.extend(holdings)
                progress.update(task, description=f"[green]Schwab: {len(holdings)} positions[/green]")
            except Exception as e:
                console.print(f"[yellow]Schwab fetch failed:[/yellow] {e}")
            progress.remove_task(task)

        if args.fidelity or fetch_both:
            task = progress.add_task("Fetching Fidelity holdings...")
            try:
                holdings = fetch_fidelity()
                all_holdings.extend(holdings)
                progress.update(task, description=f"[green]Fidelity: {len(holdings)} positions[/green]")
            except Exception as e:
                console.print(f"[yellow]Fidelity fetch failed:[/yellow] {e}")
            progress.remove_task(task)

        if not all_holdings:
            console.print("[red]No holdings fetched. Check your credentials and account IDs.[/red]")
            sys.exit(1)

        if not args.no_enrich:
            task = progress.add_task(f"Enriching {len(all_holdings)} positions with sector/geo/performance data...")
            from analysis.enrichment import enrich_holdings
            all_holdings = enrich_holdings(all_holdings)
            progress.remove_task(task)

    console.print(f"\n[bold green]Fetched {len(all_holdings)} total positions[/bold green]\n")

    from analysis.report import print_report
    print_report(all_holdings)


if __name__ == "__main__":
    main()
