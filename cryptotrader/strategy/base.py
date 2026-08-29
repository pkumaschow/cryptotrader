"""The `Strategy` contract and the position-rollback mechanism shared by all of them."""

from abc import ABC, abstractmethod
from typing import Any

from cryptotrader.models import PriceTick, Signal


class Strategy(ABC):
    """A strategy proposes orders; only the executor knows if one was placed.

    A strategy flips its own position state at the moment it emits a signal, but
    the executor can refuse the order afterwards — insufficient balance, a cap,
    the daily loss limit. Without a way back, the strategy is left describing a
    position that does not exist: it believes it is long against an entry price
    that was never paid, and the next exit signal sells coin nobody bought.

    So emitting a signal *arms* a rollback, and the trader resolves it: on a fill
    the snapshot is dropped, on a refusal the state is restored.
    """

    #: Attributes restored when an emitted order is refused. Subclasses carrying
    #: more position state than a flag should widen this.
    POSITION_ATTRS: tuple[str, ...] = ("_in_position",)

    _pending_state: dict[str, Any] | None = None

    @property
    @abstractmethod
    def name(self) -> str:
        """Identifier written to the trade log, and the key used in config."""

    @abstractmethod
    def evaluate(self, tick: PriceTick) -> Signal | None:
        """Consider a tick and optionally propose an order.

        Most ticks return None: strategies that aggregate into candles act only
        when one completes.

        Returns:
            A signal to propose, or None. An implementation that emits a signal
            must call `_arm_rollback()` before mutating its position state, or a
            refused order will leave it describing a position it does not hold.
        """

    def restore(self, db_path: str, pair: str) -> None:  # noqa: B027
        """Reload candle history and position state from DB. No-op by default."""

    def _arm_rollback(self) -> None:
        """Snapshot position state. Call immediately BEFORE mutating it."""
        self._pending_state = {
            attr: getattr(self, attr) for attr in self.POSITION_ATTRS
            if hasattr(self, attr)
        }

    def on_order_rejected(self) -> None:
        """The executor refused the order — undo the state the signal assumed.

        Restores both directions. A refused SELL must put back `_in_position`
        *and* the entry price, or the stop-loss loses the reference it measures
        against and the position can never be cut.
        """
        if self._pending_state is None:
            return
        for attr, value in self._pending_state.items():
            setattr(self, attr, value)
        self._pending_state = None

    def on_order_filled(self) -> None:
        """The order was placed — the state the signal assumed is now real."""
        self._pending_state = None
