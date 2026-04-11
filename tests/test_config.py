from unittest.mock import patch

import pytest
from pydantic import ValidationError

from cryptotrader.config import KrakenSecrets, ModeConfig, get_settings


def test_load_settings(test_config_path):
    settings = get_settings(test_config_path)
    assert settings.mode.active == "test"
    assert "BTC/USD" in settings.currencies
    assert "ETH/USD" in settings.currencies


def test_currency_config(test_config_path):
    settings = get_settings(test_config_path)
    btc = settings.currencies["BTC/USD"]
    assert btc.threshold.buy_trigger == 50000.0
    assert btc.threshold.sell_trigger == 60000.0
    assert btc.quantity == 0.001


def test_invalid_mode_raises():
    with pytest.raises(ValidationError):
        ModeConfig(active="live")


def test_valid_modes():
    ModeConfig(active="test")
    ModeConfig(active="production")


def test_production_mode_raises_without_api_keys(test_config_path, tmp_path, monkeypatch):
    """Empty API keys must cause a hard exit when mode is production."""
    monkeypatch.setattr("sys.argv", ["cryptotrader"])
    with (
        patch("cryptotrader.main.get_settings") as mock_settings,
        patch("cryptotrader.main.get_secrets") as mock_secrets,
    ):
        settings = get_settings(test_config_path)
        settings.mode.active = "production"
        settings.database.path = str(tmp_path / "main_guard.db")
        mock_settings.return_value = settings
        mock_secrets.return_value = KrakenSecrets(kraken_api_key="", kraken_api_secret="")

        from cryptotrader.main import main

        with pytest.raises(RuntimeError, match="KRAKEN_API_KEY and KRAKEN_API_SECRET"):
            main()


def test_production_mode_passes_with_api_keys(test_config_path, tmp_path, monkeypatch):
    """Valid API keys must not raise at startup in production mode."""
    monkeypatch.setattr("sys.argv", ["cryptotrader"])
    with (
        patch("cryptotrader.main.get_settings") as mock_settings,
        patch("cryptotrader.main.get_secrets") as mock_secrets,
        patch("cryptotrader.main._acquire_instance_lock", return_value=False),
        patch("cryptotrader.main.sys.exit"),
        patch("cryptotrader.main.asyncio.run"),
    ):
        settings = get_settings(test_config_path)
        settings.mode.active = "production"
        settings.database.path = str(tmp_path / "main_guard_ok.db")
        mock_settings.return_value = settings
        mock_secrets.return_value = KrakenSecrets(
            kraken_api_key="somekey", kraken_api_secret="somesecret"
        )

        from cryptotrader.main import main

        main()  # must not raise


def test_test_mode_passes_without_api_keys(test_config_path, tmp_path, monkeypatch):
    """Keys must not be required when mode is test."""
    monkeypatch.setattr("sys.argv", ["cryptotrader"])
    with (
        patch("cryptotrader.main.get_settings") as mock_settings,
        patch("cryptotrader.main.get_secrets") as mock_secrets,
        patch("cryptotrader.main._acquire_instance_lock", return_value=False),
        patch("cryptotrader.main.sys.exit"),
        patch("cryptotrader.main.asyncio.run"),
    ):
        settings = get_settings(test_config_path)
        settings.database.path = str(tmp_path / "main_test_mode.db")
        mock_settings.return_value = settings
        mock_secrets.return_value = KrakenSecrets(kraken_api_key="", kraken_api_secret="")

        from cryptotrader.main import main

        main()  # must not raise
