import pytest
from pydantic import ValidationError

from cryptotrader.config import get_settings, Settings, ModeConfig


def test_load_settings(test_config_path):
    settings = get_settings(test_config_path)
    assert settings.mode.active == "test"
    assert "BTC/USD" in settings.currencies
    assert "ETH/USD" in settings.currencies


def test_currency_config(test_config_path):
    settings = get_settings(test_config_path)
    btc = settings.currencies["BTC/USD"]
    assert btc.buy_trigger == 50000.0
    assert btc.sell_trigger == 60000.0
    assert btc.quantity == 0.001


def test_invalid_mode_raises():
    with pytest.raises(ValidationError):
        ModeConfig(active="live")


def test_valid_modes():
    ModeConfig(active="test")
    ModeConfig(active="production")
