"""
Fidelity brokerage client using OFX Direct Connect.

This uses the same OFX protocol that Quicken/Mint use to connect to Fidelity.
No special Fidelity setup required — uses your normal fidelity.com credentials.

Fidelity OFX endpoint details (well-established, same as Quicken uses):
  URL:      https://ofx.fidelity.com/ftgw/ofx/download
  ORG:      FIDELITY INVESTMENTS
  FID:      7776
  BROKERID: fidelity.com
"""

import requests
from datetime import datetime, timezone, timedelta
from typing import Optional
from io import BytesIO
from .base import Holding, BrokerClient

try:
    from ofxtools.parser import OFXTree
    OFXTOOLS_AVAILABLE = True
except ImportError:
    OFXTOOLS_AVAILABLE = False

FIDELITY_OFX_URL = "https://ofx.fidelity.com/ftgw/ofx/download"
FIDELITY_ORG = "FIDELITY INVESTMENTS"
FIDELITY_FID = "7776"
FIDELITY_BROKERID = "fidelity.com"

OFX_HEADERS = (
    "OFXHEADER:100\r\n"
    "DATA:OFXSGML\r\n"
    "VERSION:151\r\n"
    "SECURITY:NONE\r\n"
    "ENCODING:USASCII\r\n"
    "CHARSET:1252\r\n"
    "COMPRESSION:NONE\r\n"
    "OLDFILEUID:NONE\r\n"
    "NEWFILEUID:NONE\r\n"
    "\r\n"
)


def _ts(dt: datetime) -> str:
    return dt.strftime("%Y%m%d%H%M%S")


def _build_invstmt_request(username: str, password: str, account_id: str) -> str:
    now = datetime.now(timezone.utc)
    dtstart = _ts(datetime(now.year, 1, 1, tzinfo=timezone.utc))
    return (
        OFX_HEADERS
        + "<OFX>"
        + "<SIGNONMSGSRQV1><SONRQ>"
        + f"<DTCLIENT>{_ts(now)}</DTCLIENT>"
        + f"<USERID>{username}</USERID>"
        + f"<USERPASS>{password}</USERPASS>"
        + "<LANGUAGE>ENG</LANGUAGE>"
        + f"<FI><ORG>{FIDELITY_ORG}</ORG><FID>{FIDELITY_FID}</FID></FI>"
        + "<APPID>QWIN</APPID><APPVER>2700</APPVER>"
        + "</SONRQ></SIGNONMSGSRQV1>"
        + "<INVSTMTMSGSRQV1><INVSTMTTRNRQ>"
        + "<TRNUID>1001</TRNUID>"
        + "<INVSTMTRQ>"
        + f"<INVACCTFROM><BROKERID>{FIDELITY_BROKERID}</BROKERID>"
        + f"<ACCTID>{account_id}</ACCTID></INVACCTFROM>"
        + f"<INCTRAN><DTSTART>{dtstart}</DTSTART><INCLUDE>Y</INCLUDE></INCTRAN>"
        + "<INCOO>Y</INCOO>"
        + f"<INCPOS><DTASOF>{_ts(now)}</DTASOF><INCLUDE>Y</INCLUDE></INCPOS>"
        + "<INCBAL>Y</INCBAL>"
        + "</INVSTMTRQ>"
        + "</INVSTMTTRNRQ></INVSTMTMSGSRQV1>"
        + "</OFX>"
    )


class FidelityClient(BrokerClient):
    def __init__(self, username: str, password: str, account_ids: list[str]):
        if not OFXTOOLS_AVAILABLE:
            raise ImportError("ofxtools not installed. Run: pip install ofxtools")
        self.username = username
        self.password = password
        self.account_ids = account_ids

    def _fetch_account(self, account_id: str) -> list[Holding]:
        body = _build_invstmt_request(self.username, self.password, account_id)
        resp = requests.post(
            FIDELITY_OFX_URL,
            data=body.encode("ascii"),
            headers={
                "Content-Type": "application/x-ofx",
                "Accept": "application/x-ofx",
            },
            timeout=30,
        )
        resp.raise_for_status()

        parser = OFXTree()
        parser.parse(BytesIO(resp.content))
        ofx = parser.convert()

        # Build a CUSIP -> ticker lookup from the security list
        cusip_to_ticker: dict[str, str] = {}
        cusip_to_name: dict[str, str] = {}
        if ofx.security_list:
            for sec in ofx.security_list:
                cusip = sec.secid.uniqueid
                cusip_to_ticker[cusip] = getattr(sec, "ticker", "") or cusip
                cusip_to_name[cusip] = getattr(sec, "secname", cusip)

        holdings: list[Holding] = []
        for stmt in ofx.statements:
            for pos in stmt.positions:
                cusip = pos.secid.uniqueid
                symbol = cusip_to_ticker.get(cusip, cusip)
                name = cusip_to_name.get(cusip, symbol)
                units = float(pos.units)
                unit_price = float(pos.unitprice)
                mkt_val = float(pos.mktval)

                # Determine broad asset type from position class name
                pos_class = type(pos).__name__
                if "DEBT" in pos_class.upper():
                    asset_type = "BOND"
                elif "MF" in pos_class.upper() or "MUTUAL" in pos_class.upper():
                    asset_type = "FUND"
                elif "OTHER" in pos_class.upper():
                    asset_type = "OTHER"
                else:
                    asset_type = "EQUITY"

                holdings.append(
                    Holding(
                        symbol=symbol,
                        name=name,
                        quantity=units,
                        price=unit_price,
                        market_value=mkt_val,
                        account_id=account_id,
                        broker="Fidelity",
                        asset_type=asset_type,
                    )
                )
        return holdings

    def get_holdings(self) -> list[Holding]:
        all_holdings: list[Holding] = []
        for acct_id in self.account_ids:
            all_holdings.extend(self._fetch_account(acct_id))
        return all_holdings
