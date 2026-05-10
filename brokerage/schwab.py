"""
Schwab brokerage client using the official Schwab API (schwab-py).

Setup:
  1. Register a developer account at https://developer.schwab.com
  2. Create an app, set callback URL to https://127.0.0.1:8182
  3. Copy your App Key and App Secret to .env
  4. On first run, a browser will open for OAuth login - subsequent runs
     use the saved token file and refresh automatically.
"""

import os
from .base import Holding, BrokerClient

try:
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

        holdings = []
        for account in response.json():
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
