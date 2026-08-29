"""Fixed price triggers: buy below one level, sell above another.

The simplest strategy here, and mostly useful as a control when comparing the
others in test mode. It has no view on trend or volatility.
"""

from cryptotrader.config import CurrencyConfig
from cryptotrader.db import database
from cryptotrader.models import PriceTick, Side, Signal
from cryptotrader.strategy.base import Strategy


class ThresholdStrategy(Strategy):
    """Buy below a fixed price, sell above another.

    The simplest strategy here and mainly useful as a control when comparing
    the others in test mode: it has no view on trend or volatility.
    """
    @property
    def name(self) -> str:
        """Identifier written to the trade log, and the key used in config."""
        return "threshold"

    def __init__(self, config: CurrencyConfig) -> None:
        """Args:
        config: Per-pair settings; strategy parameters are read from the
        matching sub-table.
        """
        self._buy_trigger = config.threshold.buy_trigger
        self._sell_trigger = config.threshold.sell_trigger
        self._in_position = False

    def restore(self, db_path: str, pair: str) -> None:
        """Rebuild indicator history and position state from the database.

        Called once at startup. Without it a strategy would need hours of live
        ticks before its indicators were usable, and would have forgotten whether
        it holds a position.
        """
        trades = database.query_trades(db_path, pair=pair, strategy=self.name)
        if trades and trades[-1].side == Side.BUY:
            self._in_position = True

    def evaluate(self, tick: PriceTick) -> Signal | None:
        """Decide on the tick itself.

        Unlike the others this does not wait for a candle, since a fixed trigger
        has no averaging to do.

        Returns:
        A signal to propose, or None. Most ticks return None — a decision is
        only made when a candle completes.
        """
        if not self._in_position and tick.ask <= self._buy_trigger:
            self._arm_rollback()
            self._in_position = True
            return Signal.BUY
        if self._in_position and tick.bid >= self._sell_trigger:
            self._arm_rollback()
            self._in_position = False
            return Signal.SELL
        return None
