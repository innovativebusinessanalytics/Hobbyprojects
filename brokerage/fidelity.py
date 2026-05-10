"""
Fidelity brokerage client — two modes:

1. CSV import (recommended): Export your positions from Fidelity.com:
   Accounts & Trade > Portfolio > Positions > Download (top-right)
   Then run:  python main.py --fidelity-csv ~/Downloads/Portfolio_Positions.csv

2. OFX Direct Connect (legacy): May no longer work as Fidelity has
   restricted the ofx.fidelity.com endpoint for many users.
   Set FIDELITY_USERNAME / FIDELITY_PASSWORD / FIDELITY_ACCOUNT_IDS in .env
   and run:  python main.py --fidelity
"""

import re
import csv
import requests
import logging
from datetime import datetime, timezone
from pathlib import Path
from .base import Holding, BrokerClient

log = logging.getLogger(__name__)

FIDELITY_OFX_URL = "https://ofx.fidelity.com/ftgw/ofx/download"
OFX_HEADERS = (
    "OFXHEADER:100\r\nDATA:OFXSGML\r\nVERSION:151\r\nSECURITY:NONE\r\n"
    "ENCODING:USASCII\r\nCHARSET:1252\r\nCOMPRESSION:NONE\r\n"
    "OLDFILEUID:NONE\r\nNEWFILEUID:NONE\r\n\r\n"
)


# ── CSV import ────────────────────────────────────────────────────────────────

def _s(val) -> str:
    """Safe strip — handles None values from short CSV rows."""
    return (val or "").strip()


def _parse_float(s) -> float:
    return float(_s(s).replace("$", "").replace(",", "") or "0")


class FidelityCSVClient(BrokerClient):
    """Parses a CSV exported from Fidelity Positions page."""

    def __init__(self, csv_path: str):
        self.csv_path = Path(csv_path)

    def get_holdings(self) -> list[Holding]:
        holdings = []
        with self.csv_path.open(newline="", encoding="utf-8-sig") as f:
            lines = f.readlines()

        header_idx = next(
            (i for i, l in enumerate(lines) if "Symbol" in l and "Description" in l), None
        )
        if header_idx is None:
            raise ValueError("Could not find header row in Fidelity CSV — make sure you exported Positions, not transactions.")

        reader = csv.DictReader(lines[header_idx:])
        for row in reader:
            symbol = _s(row.get("Symbol"))
            # Skip blank, summary, and footer rows Fidelity appends to the CSV
            if not symbol or symbol.lower() in ("account total", "--", "pending activity"):
                continue
            if symbol.startswith("Pending"):
                continue

            try:
                quantity = _parse_float(row.get("Quantity"))
                price = _parse_float(row.get("Last Price"))
                market_value = _parse_float(row.get("Current Value"))
                cost_basis = _parse_float(row.get("Cost Basis Total")) or None
            except ValueError:
                continue

            account_id = _s(row.get("Account Number") or row.get("Account Name/Number")) or "unknown"
            desc = _s(row.get("Description")) or symbol
            asset_type = _s(row.get("Type")).upper()
            if asset_type in ("MUTUAL FUND", "MUTUAL FUNDS"):
                asset_type = "FUND"
            elif asset_type in ("BOND", "BONDS", "FIXED INCOME"):
                asset_type = "BOND"
            elif asset_type in ("CASH", "MONEY MARKET"):
                asset_type = "CASH"
            else:
                asset_type = "EQUITY"

            holdings.append(Holding(
                symbol=symbol,
                name=desc,
                quantity=quantity,
                price=price,
                market_value=market_value,
                account_id=account_id,
                broker="Fidelity",
                asset_type=asset_type,
                cost_basis=cost_basis,
            ))
            log.debug("CSV: %s qty=%.2f val=%.2f", symbol, quantity, market_value)

        log.info("Fidelity CSV: loaded %d positions from %s", len(holdings), self.csv_path)
        return holdings


# ── OFX Direct Connect ────────────────────────────────────────────────────────

def _ts(dt: datetime) -> str:
    return dt.strftime("%Y%m%d%H%M%S")


def _build_request(username: str, password: str, account_id: str) -> str:
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


def _tag(text: str, tag: str) -> str:
    m = re.search(rf"<{tag}>([^<\r\n]+)", text, re.IGNORECASE)
    return m.group(1).strip() if m else ""


def _blocks(text: str, tag: str) -> list[str]:
    return re.findall(rf"<{tag}>(.*?)</{tag}>", text, re.IGNORECASE | re.DOTALL)


def _parse_positions(sgml: str, account_id: str) -> list[Holding]:
    cusip_ticker: dict[str, str] = {}
    cusip_name: dict[str, str] = {}
    for sec in _blocks(sgml, "SECINFO"):
        cusip = _tag(sec, "UNIQUEID")
        cusip_ticker[cusip] = _tag(sec, "TICKER") or cusip
        cusip_name[cusip] = _tag(sec, "SECNAME") or cusip

    holdings: list[Holding] = []
    for pos_tag, asset_type in [("POSSTOCK", "EQUITY"), ("POSMF", "FUND"),
                                  ("POSDEBT", "BOND"), ("POSOTHER", "OTHER")]:
        for block in _blocks(sgml, pos_tag):
            cusip = _tag(block, "UNIQUEID")
            symbol = cusip_ticker.get(cusip, cusip)
            try:
                units = float(_tag(block, "UNITS") or "0")
                unit_price = float(_tag(block, "UNITPRICE") or "0")
                mkt_val = float(_tag(block, "MKTVAL") or "0")
            except ValueError:
                continue
            holdings.append(Holding(
                symbol=symbol,
                name=cusip_name.get(cusip, symbol),
                quantity=units,
                price=unit_price,
                market_value=mkt_val,
                account_id=account_id,
                broker="Fidelity",
                asset_type=asset_type,
            ))
    return holdings


class FidelityClient(BrokerClient):
    def __init__(self, username: str, password: str, account_ids: list[str]):
        self.username = username
        self.password = password
        self.account_ids = account_ids

    def _fetch_account(self, account_id: str) -> list[Holding]:
        body = _build_request(self.username, self.password, account_id)
        log.debug("OFX request to %s for account %s", FIDELITY_OFX_URL, account_id)
        resp = requests.post(
            FIDELITY_OFX_URL,
            data=body.encode("ascii"),
            headers={"Content-Type": "application/x-ofx", "Accept": "application/x-ofx"},
            timeout=30,
        )
        resp.raise_for_status()
        return _parse_positions(resp.text, account_id)

    def get_holdings(self) -> list[Holding]:
        result: list[Holding] = []
        for acct_id in self.account_ids:
            result.extend(self._fetch_account(acct_id))
        return result
