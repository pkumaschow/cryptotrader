import pytest

from cryptotrader.config import get_settings, get_secrets
from cryptotrader.db import database


@pytest.fixture(autouse=True)
def reset_settings_cache():
    """Clear lru_cache between tests so config overrides work."""
    get_settings.cache_clear()
    get_secrets.cache_clear()
    yield
    get_settings.cache_clear()
    get_secrets.cache_clear()


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

[database]
path = "test_cryptotrader.db"

[currencies."BTC/USD"]
strategy = "threshold"
quantity = 0.001

[currencies."BTC/USD".threshold]
buy_trigger = 50000.0
sell_trigger = 60000.0

[currencies."ETH/USD"]
strategy = "threshold"
quantity = 0.01

[currencies."ETH/USD".threshold]
buy_trigger = 2000.0
sell_trigger = 3000.0
""")
    return str(config)
