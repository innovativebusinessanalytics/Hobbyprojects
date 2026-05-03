#!/bin/bash
# Run this once on your machine to create the project:
#   bash setup_project.sh

mkdir -p brokerage-analyzer/brokerage brokerage-analyzer/analysis
cd brokerage-analyzer

# ── requirements.txt ──────────────────────────────────────────────
cat > requirements.txt << 'EOF'
schwab-py>=1.4.0
ofxtools>=0.9.3
yfinance>=0.2.40
pandas>=2.0.0
rich>=13.7.0
python-dotenv>=1.0.0
requests>=2.31.0
httpx>=0.27.0
EOF

# ── .gitignore ────────────────────────────────────────────────────
cat > .gitignore << 'EOF'
.env
*.token.json
__pycache__/
*.pyc
.venv/
venv/
EOF

# ── .env.example ─────────────────────────────────────────────────
cat > .env.example << 'EOF'
# === SCHWAB ===
# Register your app at https://developer.schwab.com
# Set callback URL to https://127.0.0.1:8182 in your app settings
SCHWAB_APP_KEY=your_app_key_here
SCHWAB_APP_SECRET=your_app_secret_here
SCHWAB_CALLBACK_URL=https://127.0.0.1:8182
SCHWAB_TOKEN_FILE=schwab_token.json

# === FIDELITY (OFX Direct Connect) ===
# Uses same credentials as fidelity.com login
FIDELITY_USERNAME=your_fidelity_username
FIDELITY_PASSWORD=your_fidelity_password
# Comma-separated account numbers (found on Fidelity Positions page)
FIDELITY_ACCOUNT_IDS=123456789,987654321
EOF

# ── brokerage/__init__.py ─────────────────────────────────────────
cat > brokerage/__init__.py << 'EOF'
from .base import Holding
from .schwab import SchwabClient
from .fidelity import FidelityClient

__all__ = ["Holding", "SchwabClient", "FidelityClient"]
EOF

# ── brokerage/base.py ─────────────────────────────────────────────
cat > brokerage/base.py << 'EOF'
from dataclasses import dataclass
from typing import Optional
from abc import ABC, abstractmethod


@dataclass
class Holding:
    symbol: str
    name: str
    quantity: float
    price: float
    market_value: float
    account_id: str
    broker: str
    asset_type: str = "EQUITY"
    cost_basis: Optional[float] = None
    sector: Optional[str] = None
    industry: Optional[str] = None
    country: Optional[str] = None
    currency: str = "USD"
    perf_1m: Optional[float] = None
    perf_3m: Optional[float] = None
    perf_ytd: Optional[float] = None
    perf_1y: Optional[float] = None

    @property
    def gain_loss(self) -> Optional[float]:
        if self.cost_basis is not None:
            return self.market_value - self.cost_basis
        return None

    @property
    def gain_loss_pct(self) -> Optional[float]:
        if self.cost_basis and self.cost_basis > 0:
            return (self.market_value - self.cost_basis) / self.cost_basis * 100
        return None


class BrokerClient(ABC):
    @abstractmethod
    def get_holdings(self) -> list[Holding]:
        """Return current holdings across all accounts."""
EOF

# ── brokerage/schwab.py ───────────────────────────────────────────
cat > brokerage/schwab.py << 'EOF'
"""
Schwab brokerage client using the official Schwab API (schwab-py).

Setup:
  1. Register a developer account at https://developer.schwab.com
  2. Create an app, set callback URL to https://127.0.0.1:8182
  3. Copy your App Key and App Secret to .env
  4. On first run, a browser will open for OAuth login — subsequent runs
     use the saved token file and refresh automatically.
"""

import os
from .base import Holding, BrokerClient

try:
    import schwab
    from schwab.auth import easy_client, client_from_token_file
    SCHWAB_AVAILABLE = True
except ImportError:
    SCHWAB_AVAILABLE = False

ASSET_TYPE_MAP = {
    "EQUITY": "EQUITY",
    "ETF": "EQUITY",
    "MUTUAL_FUND": "FUND",
    "FIXED_INCOME": "BOND",
    "CASH_EQUIVALENT": "CASH",
    "OPTION": "OPTION",
    "INDEX": "INDEX",
}


class SchwabClient(BrokerClient):
    def __init__(self, app_key, app_secret,
                 callback_url="https://127.0.0.1:8182",
                 token_path="schwab_token.json"):
        if not SCHWAB_AVAILABLE:
            raise ImportError("schwab-py not installed. Run: pip install schwab-py")
        self.app_key = app_key
        self.app_secret = app_secret
        self.callback_url = callback_url
        self.token_path = token_path
        self._client = None

    def _get_client(self):
        if self._client is None:
            if os.path.exists(self.token_path):
                self._client = client_from_token_file(
                    self.token_path, self.app_key, self.app_secret)
            else:
                self._client = easy_client(
                    api_key=self.app_key,
                    app_secret=self.app_secret,
                    callback_url=self.callback_url,
                    token_path=self.token_path)
        return self._client

    def get_holdings(self) -> list[Holding]:
        client = self._get_client()
        response = client.get_accounts(fields=[client.Account.Fields.POSITIONS])
        response.raise_for_status()
        accounts_data = response.json()

        holdings = []
        for account in accounts_data:
            acct = account.get("securitiesAccount", {})
            account_id = acct.get("accountNumber", "unknown")
            for pos in acct.get("positions", []):
                instrument = pos.get("instrument", {})
                symbol = instrument.get("symbol", "")
                if not symbol:
                    continue
                asset_type = ASSET_TYPE_MAP.get(instrument.get("assetType", "EQUITY"), "EQUITY")
                market_value = pos.get("marketValue", 0.0)
                quantity = pos.get("longQuantity", 0.0) - pos.get("shortQuantity", 0.0)
                avg_price = pos.get("averagePrice", 0.0)
                cost_basis = avg_price * abs(quantity) if avg_price else None
                current_price = market_value / abs(quantity) if quantity else 0.0
                holdings.append(Holding(
                    symbol=symbol,
                    name=instrument.get("description", symbol),
                    quantity=quantity,
                    price=current_price,
                    market_value=market_value,
                    account_id=account_id,
                    broker="Schwab",
                    asset_type=asset_type,
                    cost_basis=cost_basis,
                ))
        return holdings
EOF

# ── brokerage/fidelity.py ─────────────────────────────────────────
cat > brokerage/fidelity.py << 'EOF'
"""
Fidelity brokerage client using OFX Direct Connect.
No special Fidelity setup required — uses your normal fidelity.com credentials.
"""

import requests
from datetime import datetime, timezone
from io import BytesIO
from .base import Holding, BrokerClient

try:
    from ofxtools.parser import OFXTree
    OFXTOOLS_AVAILABLE = True
except ImportError:
    OFXTOOLS_AVAILABLE = False

FIDELITY_OFX_URL = "https://ofx.fidelity.com/ftgw/ofx/download"
OFX_HEADERS = (
    "OFXHEADER:100\r\nDATA:OFXSGML\r\nVERSION:151\r\nSECURITY:NONE\r\n"
    "ENCODING:USASCII\r\nCHARSET:1252\r\nCOMPRESSION:NONE\r\n"
    "OLDFILEUID:NONE\r\nNEWFILEUID:NONE\r\n\r\n"
)


def _ts(dt):
    return dt.strftime("%Y%m%d%H%M%S")


def _build_request(username, password, account_id):
    now = datetime.now(timezone.utc)
    dtstart = _ts(datetime(now.year, 1, 1, tzinfo=timezone.utc))
    return (
        OFX_HEADERS + "<OFX>"
        + "<SIGNONMSGSRQV1><SONRQ>"
        + f"<DTCLIENT>{_ts(now)}</DTCLIENT>"
        + f"<USERID>{username}</USERID><USERPASS>{password}</USERPASS>"
        + "<LANGUAGE>ENG</LANGUAGE>"
        + "<FI><ORG>FIDELITY INVESTMENTS</ORG><FID>7776</FID></FI>"
        + "<APPID>QWIN</APPID><APPVER>2700</APPVER>"
        + "</SONRQ></SIGNONMSGSRQV1>"
        + "<INVSTMTMSGSRQV1><INVSTMTTRNRQ><TRNUID>1001</TRNUID><INVSTMTRQ>"
        + f"<INVACCTFROM><BROKERID>fidelity.com</BROKERID><ACCTID>{account_id}</ACCTID></INVACCTFROM>"
        + f"<INCTRAN><DTSTART>{dtstart}</DTSTART><INCLUDE>Y</INCLUDE></INCTRAN>"
        + f"<INCOO>Y</INCOO><INCPOS><DTASOF>{_ts(now)}</DTASOF><INCLUDE>Y</INCLUDE></INCPOS>"
        + "<INCBAL>Y</INCBAL></INVSTMTRQ></INVSTMTTRNRQ></INVSTMTMSGSRQV1></OFX>"
    )


class FidelityClient(BrokerClient):
    def __init__(self, username, password, account_ids):
        if not OFXTOOLS_AVAILABLE:
            raise ImportError("ofxtools not installed. Run: pip install ofxtools")
        self.username = username
        self.password = password
        self.account_ids = account_ids

    def _fetch_account(self, account_id):
        body = _build_request(self.username, self.password, account_id)
        resp = requests.post(FIDELITY_OFX_URL, data=body.encode("ascii"),
                             headers={"Content-Type": "application/x-ofx",
                                      "Accept": "application/x-ofx"}, timeout=30)
        resp.raise_for_status()
        parser = OFXTree()
        parser.parse(BytesIO(resp.content))
        ofx = parser.convert()

        cusip_to_ticker, cusip_to_name = {}, {}
        if ofx.security_list:
            for sec in ofx.security_list:
                c = sec.secid.uniqueid
                cusip_to_ticker[c] = getattr(sec, "ticker", "") or c
                cusip_to_name[c] = getattr(sec, "secname", c)

        holdings = []
        for stmt in ofx.statements:
            for pos in stmt.positions:
                c = pos.secid.uniqueid
                symbol = cusip_to_ticker.get(c, c)
                pos_class = type(pos).__name__.upper()
                if "DEBT" in pos_class:
                    asset_type = "BOND"
                elif "MF" in pos_class:
                    asset_type = "FUND"
                else:
                    asset_type = "EQUITY"
                holdings.append(Holding(
                    symbol=symbol,
                    name=cusip_to_name.get(c, symbol),
                    quantity=float(pos.units),
                    price=float(pos.unitprice),
                    market_value=float(pos.mktval),
                    account_id=account_id,
                    broker="Fidelity",
                    asset_type=asset_type,
                ))
        return holdings

    def get_holdings(self):
        result = []
        for acct_id in self.account_ids:
            result.extend(self._fetch_account(acct_id))
        return result
EOF

# ── analysis/__init__.py ──────────────────────────────────────────
cat > analysis/__init__.py << 'EOF'
from .enrichment import enrich_holdings
from .report import print_report

__all__ = ["enrich_holdings", "print_report"]
EOF

# ── analysis/enrichment.py ────────────────────────────────────────
cat > analysis/enrichment.py << 'EOF'
import yfinance as yf
from concurrent.futures import ThreadPoolExecutor, as_completed
from brokerage.base import Holding

CASH_LIKE = {"SPAXX", "FDRXX", "FCASH", "MMDA1", "SWVXX", "SNSXX"}
_PERIODS = {"1mo": "perf_1m", "3mo": "perf_3m", "ytd": "perf_ytd", "1y": "perf_1y"}


def _pct(series):
    if series is None or len(series) < 2:
        return None
    f, l = series.iloc[0], series.iloc[-1]
    return round((l / f - 1) * 100, 2) if f else None


def _enrich_one(h: Holding) -> Holding:
    if h.asset_type == "CASH" or h.symbol in CASH_LIKE:
        h.sector, h.country = "Cash & Equivalents", "N/A"
        return h
    try:
        info = yf.Ticker(h.symbol).info or {}
        h.sector = info.get("sector") or _infer(info)
        h.industry = info.get("industry")
        h.country = info.get("country", "United States")
        for period, attr in _PERIODS.items():
            try:
                hist = yf.Ticker(h.symbol).history(period=period)
                setattr(h, attr, _pct(hist["Close"]) if not hist.empty else None)
            except Exception:
                pass
    except Exception:
        pass
    return h


def _infer(info):
    qt, cat = info.get("quoteType", "").upper(), info.get("category", "").upper()
    if "BOND" in qt or "FIXED" in cat or "BOND" in cat:
        return "Fixed Income"
    if "ETF" in qt or "MUTUALFUND" in qt:
        return "Diversified"
    return "Unknown"


def enrich_holdings(holdings, max_workers=8):
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_enrich_one, h): h for h in holdings}
        return [f.result() for f in as_completed(futures)]
EOF

# ── analysis/report.py ────────────────────────────────────────────
cat > analysis/report.py << 'EOF'
from collections import defaultdict
from rich.console import Console
from rich.table import Table
from rich import box
from rich.text import Text
from brokerage.base import Holding

console = Console()


def _val(v, fmt=",.0f", prefix="$"):
    return "—" if v is None else f"{prefix}{v:{fmt}}"

def _pct(v):
    if v is None: return Text("—", style="dim")
    return Text(f"{'+'if v>=0 else ''}{v:.1f}%", style="green" if v >= 0 else "red")

def _bar(pct, w=20):
    n = round(pct / 100 * w)
    return "█" * n + "░" * (w - n)


def _holdings_table(holdings):
    t = Table(title="Holdings", box=box.ROUNDED, header_style="bold cyan")
    for col, kw in [("Symbol",{"style":"bold white","width":10}),("Name",{"width":28}),
                    ("Broker/Acct",{"width":18}),("Sector",{"width":20}),("Country",{"width":15}),
                    ("Qty",{"justify":"right","width":10}),("Price",{"justify":"right","width":10}),
                    ("Value",{"justify":"right","width":12}),("G/L%",{"justify":"right","width":8}),
                    ("1Y",{"justify":"right","width":8})]:
        t.add_column(col, **kw)
    total = sum(h.market_value for h in holdings)
    for h in sorted(holdings, key=lambda x: -x.market_value):
        t.add_row(h.symbol, h.name[:28], f"{h.broker} {h.account_id[-4:]}",
                  h.sector or "—", h.country or "—",
                  f"{h.quantity:,.2f}", _val(h.price, ",.2f"),
                  _val(h.market_value), _pct(h.gain_loss_pct), _pct(h.perf_1y))
    console.print(t)
    console.print(f"  [bold]Total:[/bold] [green]{_val(total)}[/green]\n")


def _alloc_table(holdings, key, title):
    totals, grand = defaultdict(float), 0.0
    for h in holdings:
        k = getattr(h, key) or "Unknown"
        totals[k] += h.market_value
        grand += h.market_value
    t = Table(title=title, box=box.SIMPLE, header_style="bold cyan")
    t.add_column(title.split()[0], width=30)
    t.add_column("Value", justify="right", width=14)
    t.add_column("Weight", justify="right", width=8)
    t.add_column("", width=22)
    for k, v in sorted(totals.items(), key=lambda x: -x[1]):
        pct = v / grand * 100 if grand else 0
        t.add_row(k, _val(v), f"{pct:.1f}%", _bar(pct))
    console.print(t)


def _perf_table(holdings):
    t = Table(title="Performance", box=box.ROUNDED, header_style="bold cyan")
    for col, kw in [("Symbol",{"style":"bold white","width":10}),("Name",{"width":28}),
                    ("1M",{"justify":"right","width":8}),("3M",{"justify":"right","width":8}),
                    ("YTD",{"justify":"right","width":8}),("1Y",{"justify":"right","width":8}),
                    ("Cost Basis",{"justify":"right","width":12}),("G/L $",{"justify":"right","width":12}),
                    ("G/L %",{"justify":"right","width":8})]:
        t.add_column(col, **kw)
    for h in sorted(holdings, key=lambda x: -x.market_value):
        gl = h.gain_loss
        gl_str = Text("—") if gl is None else Text(f"{'+'if gl>=0 else''}${gl:,.0f}",
                                                    style="green" if gl >= 0 else "red")
        t.add_row(h.symbol, h.name[:28], _pct(h.perf_1m), _pct(h.perf_3m),
                  _pct(h.perf_ytd), _pct(h.perf_1y),
                  _val(h.cost_basis) if h.cost_basis else "—", gl_str, _pct(h.gain_loss_pct))
    console.print(t)


def _wp(holdings, attr):
    tv = sum(h.market_value for h in holdings if getattr(h, attr) is not None)
    if not tv: return None
    return sum(h.market_value / tv * getattr(h, attr)
               for h in holdings if getattr(h, attr) is not None)


def print_report(holdings):
    console.rule("[bold cyan]Portfolio Analysis[/bold cyan]")
    console.print()
    _holdings_table(holdings)
    _alloc_table(holdings, "sector", "Sector Allocation")
    console.print()
    _alloc_table(holdings, "country", "Geography Allocation")
    console.print()
    _perf_table(holdings)
    console.print()
    console.rule("[bold cyan]Portfolio-Level Performance (value-weighted)[/bold cyan]")
    t = Table(box=box.SIMPLE, header_style="bold cyan")
    for c, kw in [("",{"width":30}),("1M",{"justify":"right","width":8}),
                  ("3M",{"justify":"right","width":8}),("YTD",{"justify":"right","width":8}),
                  ("1Y",{"justify":"right","width":8})]:
        t.add_column(c, **kw)
    t.add_row("Your Portfolio", _pct(_wp(holdings,"perf_1m")), _pct(_wp(holdings,"perf_3m")),
              _pct(_wp(holdings,"perf_ytd")), _pct(_wp(holdings,"perf_1y")))
    console.print(t)
    console.print()
EOF

# ── main.py ───────────────────────────────────────────────────────
cat > main.py << 'EOF'
#!/usr/bin/env python3
"""
Usage:
  cp .env.example .env        # fill in credentials
  pip install -r requirements.txt
  python main.py              # both brokers
  python main.py --schwab     # Schwab only
  python main.py --fidelity   # Fidelity only
  python main.py --no-enrich  # skip yfinance enrichment
"""

import argparse, sys, os
from dotenv import load_dotenv
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

load_dotenv()
console = Console()


def _env(*names):
    missing = [n for n in names if not os.getenv(n)]
    if missing:
        console.print(f"[red]Missing: {', '.join(missing)}[/red] — copy .env.example to .env")
        sys.exit(1)
    return {n: os.environ[n] for n in names}


def fetch_schwab():
    from brokerage.schwab import SchwabClient
    e = _env("SCHWAB_APP_KEY", "SCHWAB_APP_SECRET")
    return SchwabClient(e["SCHWAB_APP_KEY"], e["SCHWAB_APP_SECRET"],
                        os.getenv("SCHWAB_CALLBACK_URL", "https://127.0.0.1:8182"),
                        os.getenv("SCHWAB_TOKEN_FILE", "schwab_token.json")).get_holdings()


def fetch_fidelity():
    from brokerage.fidelity import FidelityClient
    e = _env("FIDELITY_USERNAME", "FIDELITY_PASSWORD", "FIDELITY_ACCOUNT_IDS")
    ids = [a.strip() for a in e["FIDELITY_ACCOUNT_IDS"].split(",") if a.strip()]
    return FidelityClient(e["FIDELITY_USERNAME"], e["FIDELITY_PASSWORD"], ids).get_holdings()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--schwab", action="store_true")
    p.add_argument("--fidelity", action="store_true")
    p.add_argument("--no-enrich", action="store_true")
    args = p.parse_args()
    both = not args.schwab and not args.fidelity

    all_holdings = []
    with Progress(SpinnerColumn(), TextColumn("{task.description}"), transient=True) as prog:
        for name, fn, flag in [("Schwab", fetch_schwab, args.schwab or both),
                                ("Fidelity", fetch_fidelity, args.fidelity or both)]:
            if not flag:
                continue
            t = prog.add_task(f"Fetching {name}...")
            try:
                h = fn()
                all_holdings.extend(h)
                prog.update(t, description=f"[green]{name}: {len(h)} positions[/green]")
            except Exception as e:
                console.print(f"[yellow]{name} failed:[/yellow] {e}")
            prog.remove_task(t)

        if not all_holdings:
            console.print("[red]No holdings fetched.[/red]")
            sys.exit(1)

        if not args.no_enrich:
            t = prog.add_task(f"Enriching {len(all_holdings)} positions...")
            from analysis.enrichment import enrich_holdings
            all_holdings = enrich_holdings(all_holdings)
            prog.remove_task(t)

    console.print(f"\n[bold green]{len(all_holdings)} positions loaded[/bold green]\n")
    from analysis.report import print_report
    print_report(all_holdings)


if __name__ == "__main__":
    main()
EOF

echo ""
echo "✓ Project created in: $(pwd)"
echo ""
echo "Next steps:"
echo "  cd brokerage-analyzer"
echo "  pip install -r requirements.txt"
echo "  cp .env.example .env   # then fill in your credentials"
echo "  python main.py"
