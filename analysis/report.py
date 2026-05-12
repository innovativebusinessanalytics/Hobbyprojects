"""
Terminal report generation using Rich.
Produces four sections:
  1. Holdings table (by broker/account)
  2. Sector allocation vs S&P 500
  3. Equity region breakdown
  4. Geography allocation
  5. Performance summary
"""

from collections import defaultdict
from rich.console import Console
from rich.table import Table
from rich import box
from rich.text import Text
from brokerage.base import Holding
from analysis.regions import REGION_ORDER, SUB_REGION_ORDER

console = Console()

# Approximate S&P 500 GICS sector weights (updated periodically)
SP500_SECTOR_WEIGHTS: dict[str, float] = {
    "Basic Materials": 1.90,
    "Communication Services": 10.48,
    "Consumer Cyclical": 10.00,
    "Consumer Defensive": 5.25,
    "Energy": 4.01,
    "Financial Services": 12.34,
    "Healthcare": 9.47,
    "Industrials": 8.47,
    "Real Estate": 1.95,
    "Technology": 33.57,
    "Utilities": 2.54,
}


def _fmt_val(v: float | None, fmt: str = ",.0f", prefix: str = "$") -> str:
    if v is None:
        return "—"
    return f"{prefix}{v:{fmt}}"


def _fmt_pct(v: float | None) -> Text:
    if v is None:
        return Text("—", style="dim")
    color = "green" if v >= 0 else "red"
    sign = "+" if v >= 0 else ""
    return Text(f"{sign}{v:.1f}%", style=color)


def _bar(pct: float, width: int = 20) -> str:
    filled = round(pct / 100 * width)
    return "█" * filled + "░" * (width - filled)


def _holdings_table(holdings: list[Holding]) -> None:
    table = Table(
        title="Holdings",
        box=box.ROUNDED,
        show_lines=False,
        header_style="bold cyan",
    )
    table.add_column("Symbol", style="bold white", width=10)
    table.add_column("Name", width=28)
    table.add_column("Broker / Account", width=20)
    table.add_column("Sector", width=20)
    table.add_column("Country", width=15)
    table.add_column("Qty", justify="right", width=10)
    table.add_column("Price", justify="right", width=10)
    table.add_column("Value", justify="right", width=12)
    table.add_column("G/L%", justify="right", width=8)
    table.add_column("1Y Perf", justify="right", width=9)

    total_value = sum(h.market_value for h in holdings)

    for h in sorted(holdings, key=lambda x: -x.market_value):
        acct_label = f"{h.broker} {h.account_id[-4:]}"
        table.add_row(
            h.symbol,
            h.name[:28],
            acct_label,
            h.sector or "—",
            h.country or "—",
            f"{h.quantity:,.2f}",
            _fmt_val(h.price, fmt=",.2f"),
            _fmt_val(h.market_value),
            _fmt_pct(h.gain_loss_pct),
            _fmt_pct(h.perf_1y),
        )

    console.print(table)
    console.print(f"  [bold]Total portfolio value:[/bold]  [green]{_fmt_val(total_value)}[/green]\n")


def _allocation_table(holdings: list[Holding], group_key: str, title: str) -> None:
    totals: dict[str, float] = defaultdict(float)
    grand_total = 0.0
    for h in holdings:
        key = getattr(h, group_key) or "Unknown"
        totals[key] += h.market_value
        grand_total += h.market_value

    table = Table(title=title, box=box.SIMPLE, header_style="bold cyan")
    table.add_column(title.split()[0], width=30)
    table.add_column("Value", justify="right", width=14)
    table.add_column("Weight", justify="right", width=8)
    table.add_column("", width=22)

    for key, val in sorted(totals.items(), key=lambda x: -x[1]):
        pct = val / grand_total * 100 if grand_total else 0
        table.add_row(key, _fmt_val(val), f"{pct:.1f}%", _bar(pct))

    console.print(table)


def _dual_bar(port_pct: float, sp_pct: float, width: int = 18) -> Text:
    """Two stacked colored bars: magenta for portfolio, green for S&P 500."""
    max_pct = 40.0  # scale so 40% fills the bar
    p_fill = min(round(port_pct / max_pct * width), width)
    s_fill = min(round(sp_pct / max_pct * width), width)
    t = Text()
    t.append("█" * p_fill + "░" * (width - p_fill), style="magenta")
    t.append(" ")
    t.append("█" * s_fill + "░" * (width - s_fill), style="green")
    return t


def _equity_sector_table(holdings: list[Holding]) -> None:
    """Sector breakdown vs S&P 500 benchmark with dual bar chart."""
    equity = [
        h for h in holdings
        if h.asset_type not in ("CASH", "BOND", "OPTION")
        and h.sector not in ("Cash & Equivalents", "Fixed Income", "Options", "Diversified", None)
    ]
    total = sum(h.market_value for h in equity)
    if not total:
        return

    by_sector: dict[str, float] = defaultdict(float)
    for h in equity:
        by_sector[h.sector] += h.market_value

    # Union of portfolio sectors and S&P sectors, sorted alphabetically
    all_sectors = sorted(set(by_sector) | set(SP500_SECTOR_WEIGHTS))

    table = Table(
        title="Equity Sector vs S&P 500",
        box=box.SIMPLE,
        header_style="bold cyan",
        show_header=True,
    )
    table.add_column("Sector", width=24)
    table.add_column("Portfolio", justify="right", width=10)
    table.add_column("S&P 500", justify="right", width=10)
    table.add_column("[magenta]Portfolio[/magenta]  [green]S&P 500[/green]", width=40, no_wrap=True)

    for sector in all_sectors:
        port_pct = by_sector.get(sector, 0.0) / total * 100
        sp_pct = SP500_SECTOR_WEIGHTS.get(sector, 0.0)

        port_str = Text(f"{port_pct:.2f}%", style="magenta" if port_pct else "dim")
        sp_str = Text(f"{sp_pct:.2f}%" if sp_pct else "—", style="green" if sp_pct else "dim")

        table.add_row(sector, port_str, sp_str, _dual_bar(port_pct, sp_pct))

    console.print(table)
    console.print(
        "  [dim]S&P 500 weights are approximate and updated periodically.[/dim]\n"
    )


def _performance_table(holdings: list[Holding]) -> None:
    table = Table(title="Performance Summary", box=box.ROUNDED, header_style="bold cyan")
    table.add_column("Symbol", style="bold white", width=10)
    table.add_column("Name", width=28)
    table.add_column("1M", justify="right", width=8)
    table.add_column("3M", justify="right", width=8)
    table.add_column("YTD", justify="right", width=8)
    table.add_column("1Y", justify="right", width=8)
    table.add_column("Cost Basis", justify="right", width=12)
    table.add_column("G/L $", justify="right", width=12)
    table.add_column("G/L %", justify="right", width=8)

    for h in sorted(holdings, key=lambda x: -x.market_value):
        gl = h.gain_loss
        gl_str = Text("—")
        if gl is not None:
            color = "green" if gl >= 0 else "red"
            sign = "+" if gl >= 0 else ""
            gl_str = Text(f"{sign}${gl:,.0f}", style=color)

        table.add_row(
            h.symbol,
            h.name[:28],
            _fmt_pct(h.perf_1m),
            _fmt_pct(h.perf_3m),
            _fmt_pct(h.perf_ytd),
            _fmt_pct(h.perf_1y),
            _fmt_val(h.cost_basis) if h.cost_basis else "—",
            gl_str,
            _fmt_pct(h.gain_loss_pct),
        )

    console.print(table)


def _weighted_perf(holdings: list[Holding], attr: str) -> float | None:
    total_val = sum(h.market_value for h in holdings if getattr(h, attr) is not None)
    if total_val == 0:
        return None
    return sum(
        h.market_value / total_val * getattr(h, attr)
        for h in holdings
        if getattr(h, attr) is not None
    )


def _equity_region_table(holdings: list[Holding]) -> None:
    """Hierarchical equity region breakdown (US / Developed / Emerging / Other)."""
    equity = [h for h in holdings if h.asset_type not in ("CASH", "BOND", "OPTION")
              and h.sector not in ("Cash & Equivalents", "Fixed Income")]
    total = sum(h.market_value for h in equity)
    if not total:
        return

    # Accumulate value by (region, sub_region)
    by_sub: dict[tuple[str, str], float] = defaultdict(float)
    for h in equity:
        r = h.region or "Other"
        sr = h.sub_region or "Other"
        by_sub[(r, sr)] += h.market_value

    by_region: dict[str, float] = defaultdict(float)
    for (r, _), v in by_sub.items():
        by_region[r] += v

    table = Table(title="Equity Region", box=box.SIMPLE, header_style="bold cyan", show_header=True)
    table.add_column("Region", width=28)
    table.add_column("Weight", justify="right", width=8)
    table.add_column("", width=22)

    for region in REGION_ORDER:
        rv = by_region.get(region, 0)
        if not rv:
            continue
        pct = rv / total * 100
        table.add_row(
            f"[bold]{region}[/bold]",
            f"[bold]{pct:.2f}%[/bold]",
            f"[bold]{_bar(pct)}[/bold]",
        )
        # Sub-regions
        for sub in SUB_REGION_ORDER:
            sv = by_sub.get((region, sub), 0)
            if not sv:
                continue
            spct = sv / total * 100
            table.add_row(f"  {sub}", f"{spct:.2f}%", _bar(spct, 14))

    console.print(table)


def print_report(holdings: list[Holding]) -> None:
    console.rule("[bold cyan]Portfolio Analysis[/bold cyan]")
    console.print()

    _holdings_table(holdings)
    _equity_sector_table(holdings)
    _equity_region_table(holdings)
    console.print()
    _allocation_table(holdings, "country", "Geography Allocation")
    console.print()
    _performance_table(holdings)

    console.print()
    console.rule("[bold cyan]Portfolio-Level Performance (value-weighted)[/bold cyan]")
    perf_table = Table(box=box.SIMPLE, header_style="bold cyan", show_header=True)
    perf_table.add_column("", width=30)
    perf_table.add_column("1M", justify="right", width=8)
    perf_table.add_column("3M", justify="right", width=8)
    perf_table.add_column("YTD", justify="right", width=8)
    perf_table.add_column("1Y", justify="right", width=8)

    perf_table.add_row(
        "Your Portfolio",
        _fmt_pct(_weighted_perf(holdings, "perf_1m")),
        _fmt_pct(_weighted_perf(holdings, "perf_3m")),
        _fmt_pct(_weighted_perf(holdings, "perf_ytd")),
        _fmt_pct(_weighted_perf(holdings, "perf_1y")),
    )
    console.print(perf_table)
    console.print()
