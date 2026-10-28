import pytest
from aioresponses import aioresponses
from yarl import URL

from cryptotrader.exchange.kraken_rest import KrakenRest

# These drive _post itself; aioresponses intercepts at the aiohttp transport, so
# nothing leaves the machine. Every other test is blocked by conftest.
pytestmark = pytest.mark.exchange_http


@pytest.mark.asyncio
async def test_place_order_returns_txid():
    client = KrakenRest("test_key", "dGVzdF9zZWNyZXQ=")  # base64-safe dummy secret
    with aioresponses() as m:
        m.post(
            "https://api.kraken.com/0/private/AddOrder",
            payload={"error": [], "result": {"txid": ["TXID-1234"]}},
        )
        txid = await client.place_order("BTC/USD", "buy", 0.001)
    assert txid == "TXID-1234"
    await client.close()


@pytest.mark.asyncio
async def test_place_order_raises_on_kraken_error():
    client = KrakenRest("test_key", "dGVzdF9zZWNyZXQ=")
    with aioresponses() as m:
        m.post(
            "https://api.kraken.com/0/private/AddOrder",
            payload={"error": ["EGeneral:Internal error"], "result": {}},
        )
        with pytest.raises(RuntimeError, match="Kraken API error"):
            await client.place_order("BTC/USD", "buy", 0.001)
    await client.close()


@pytest.mark.asyncio
async def test_invalid_nonce_is_retried_once_with_fresh_nonce():
    client = KrakenRest("test_key", "dGVzdF9zZWNyZXQ=")
    url = "https://api.kraken.com/0/private/Balance"
    with aioresponses() as m:
        m.post(url, payload={"error": ["EAPI:Invalid nonce"], "result": {}})
        m.post(url, payload={"error": [], "result": {"ZUSD": "100.5"}})
        balance = await client.get_balance()
        nonces = [int(call.kwargs["data"]["nonce"]) for call in m.requests[("POST", URL(url))]]
    assert balance == {"ZUSD": 100.5}
    assert len(nonces) == 2 and nonces[1] > nonces[0]
    await client.close()


@pytest.mark.asyncio
async def test_invalid_nonce_twice_surfaces():
    client = KrakenRest("test_key", "dGVzdF9zZWNyZXQ=")
    url = "https://api.kraken.com/0/private/Balance"
    with aioresponses() as m:
        m.post(url, payload={"error": ["EAPI:Invalid nonce"], "result": {}})
        m.post(url, payload={"error": ["EAPI:Invalid nonce"], "result": {}})
        m.post(url, payload={"error": [], "result": {}})
        with pytest.raises(RuntimeError, match="Invalid nonce"):
            await client.get_balance()
    await client.close()


@pytest.mark.asyncio
async def test_other_kraken_errors_are_not_retried():
    client = KrakenRest("test_key", "dGVzdF9zZWNyZXQ=")
    url = "https://api.kraken.com/0/private/AddOrder"
    with aioresponses() as m:
        m.post(url, payload={"error": ["EOrder:Insufficient funds"], "result": {}})
        m.post(url, payload={"error": [], "result": {"txid": ["SHOULD-NOT-REACH"]}})
        with pytest.raises(RuntimeError, match="Insufficient funds"):
            await client.place_order("BTC/USD", "buy", 0.001)
    await client.close()
