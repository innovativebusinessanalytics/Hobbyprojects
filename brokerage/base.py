from dataclasses import dataclass, field
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
    # Enriched by analysis layer
    sector: Optional[str] = None
    industry: Optional[str] = None
    country: Optional[str] = None
    currency: str = "USD"
    perf_1m: Optional[float] = None
    perf_3m: Optional[float] = None
    perf_ytd: Optional[float] = None
    perf_1y: Optional[float] = None
    region: Optional[str] = None
    sub_region: Optional[str] = None

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
