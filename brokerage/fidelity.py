"""
Fidelity brokerage client using OFX Direct Connect.

This uses the same OFX protocol that Quicken/Mint use to connect to Fidelity.
No special Fidelity setup required — uses your normal fidelity.com credentials.
Parses the OFX SGML response with stdlib xml.etree (no ofxtools dependency).

Fidelity OFX endpoint details (well-established, same as Quicken uses):
  URL:      https://ofx.fidelity.com/ftgw/ofx/download
  ORG:      FIDELITY INVESTMENTS
  FID:      7776
  BROKERID: fidelity.com
"""

import re
import requests
from datetime import datetime, timezone
from .base import Holding, BrokerClient

FIDELITY_OFX_URL = "https://ofx.fidelity.com/ftgw/ofx/download"

OFX_HEADERS = (
    "OFXHEADER:100\r\nDATA:OFXSGML\r\nVERSION:151\r\nSECURITY:NONE\r\n"
    "ENCODING:USASCII\r\nCHARSET:1252\r\nCOMPRESSION:NONE\r\n"
    "OLDFILEUID:NONE\r\nNEWFILEUID:NONE\r\n\r\n"
)


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
    """Extract the first value of a leaf OFX SGML tag (no closing tag)."""
    m = re.search(rf"<{tag}>([^<\r\n]+)", text, re.IGNORECASE)
    return m.group(1).strip() if m else ""


def _blocks(text: str, tag: str) -> list[str]:
    """Extract all text blocks enclosed by <TAG>...</TAG>."""
    return re.findall(rf"<{tag}>(.*?)</{tag}>", text, re.IGNORECASE | re.DOTALL)


def _parse_positions(sgml: str, account_id: str) -> list[Holding]:
    """Parse OFX SGML investment positions without external dependencies."""
    # Build CUSIP -> (ticker, name) from SECLIST
    cusip_ticker: dict[str, str] = {}
    cusip_name: dict[str, str] = {}
    for sec in _blocks(sgml, "SECINFO"):
        cusip = _tag(sec, "UNIQUEID")
        ticker = _tag(sec, "TICKER") or cusip
        name = _tag(sec, "SECNAME") or ticker
        cusip_ticker[cusip] = ticker
        cusip_name[cusip] = name

    holdings: list[Holding] = []
    pos_tags = ["POSSTOCK", "POSMF", "POSDEBT", "POSOTHER"]
    for pos_tag in pos_tags:
        for block in _blocks(sgml, pos_tag):
            cusip = _tag(block, "UNIQUEID")
            symbol = cusip_ticker.get(cusip, cusip)
            name = cusip_name.get(cusip, symbol)
            try:
                units = float(_tag(block, "UNITS") or "0")
                unit_price = float(_tag(block, "UNITPRICE") or "0")
                mkt_val = float(_tag(block, "MKTVAL") or "0")
            except ValueError:
                continue

            if pos_tag == "POSDEBT":
                asset_type = "BOND"
            elif pos_tag == "POSMF":
                asset_type = "FUND"
            elif pos_tag == "POSOTHER":
                asset_type = "OTHER"
            else:
                asset_type = "EQUITY"

            holdings.append(Holding(
                symbol=symbol,
                name=name,
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
