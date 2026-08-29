import inspect
from types import SimpleNamespace

import aiohttp
import pytest

from cryptotrader.config import get_secrets, get_settings
from cryptotrader.db import database

# aiohttp 3.14 made `stream_writer` a required keyword-only argument of
# ClientResponse.__init__. aioresponses (0.7.9, latest) still constructs the
# response without it, so every mocked HTTP response raises TypeError and the
# kraken_rest tests fail. aiohttp only reads `stream_writer.output_size`, so a
# stub satisfies it. This mirrors the upstream fix in
# pnuckowski/aioresponses#288 — delete this block once that ships and the dev
# pin can move.
#
# Without it the alternative is pinning aiohttp below 3.14, which reintroduces
# CVE-2026-69244 and fails the Trivy dependency gate in CI.
if "stream_writer" in inspect.signature(aiohttp.ClientResponse.__init__).parameters:
    _orig_client_response_init = aiohttp.ClientResponse.__init__

    def _client_response_init(self, *args, **kwargs):
        kwargs.setdefault("stream_writer", SimpleNamespace(output_size=0))
        return _orig_client_response_init(self, *args, **kwargs)

    aiohttp.ClientResponse.__init__ = _client_response_init


@pytest.fixture(autouse=True)
def reset_settings_cache():
    """Clear lru_cache between tests so config overrides work."""
    get_settings.cache_clear()
    get_secrets.cache_clear()
    yield
    get_settings.cache_clear()
    get_secrets.cache_clear()


@pytest.fixture(autouse=True)
def block_exchange_network(monkeypatch, request):
    """Refuse every outbound call to Kraken unless a test opts in.

    `config/settings.toml` carries `active = "production"`, so any test reaching
    `get_settings()` without pinning the mode takes the production path, and
    `TradeExecutor` then attempts a real balance check. That has already
    happened once: a test in test_maker_entries.py hit the live API and failed
    only because no credentials exist on this machine. Somewhere that has them
    — the Pi holds live keys and a production config, with tests/ deployed
    beside them — the same test could place a real order.

    `_post` is the single network chokepoint: place_order, place_post_only_limit,
    order_status, cancel_order and get_balance all route through it. Blocking it
    is therefore complete, and turns a silent trade into a loud failure.

    Opt out with `@pytest.mark.exchange_http` for tests that deliberately drive
    the HTTP layer against a mock transport.
    """
    if request.node.get_closest_marker("exchange_http"):
        return

    from cryptotrader.exchange.kraken_rest import KrakenRest

    async def _refuse(self, endpoint, data):
        raise AssertionError(
            f"Test attempted a live Kraken API call ({endpoint}). Tests must not "
            f"reach the exchange: inject a fake with set_rest_client(), or mark "
            f"the test @pytest.mark.exchange_http if it drives the HTTP layer "
            f"against a mock transport."
        )

    monkeypatch.setattr(KrakenRest, "_post", _refuse)


@pytest.fixture
def tmp_db(tmp_path):
    db_path = str(tmp_path / "test.db")
    database.init_db(db_path)
    return db_path


@pytest.fixture
def test_config_path(tmp_path):
    """Write a minimal test settings.toml and return its path."""
    config = tmp_path / "settings.toml"
    config.write_text("""
[mode]
active = "test"
max_daily_loss_usd = 50.0

[database]
path = "test_cryptotrader.db"

[currencies."BTC/USD"]
strategy = "threshold"
quantity = 0.001
max_order_usd = 500.0

[currencies."BTC/USD".threshold]
buy_trigger = 50000.0
sell_trigger = 60000.0

[currencies."ETH/USD"]
strategy = "threshold"
quantity = 0.01
max_order_usd = 500.0

[currencies."ETH/USD".threshold]
buy_trigger = 2000.0
sell_trigger = 3000.0
""")
    return str(config)
