import pytest
from aioresponses import aioresponses

from cryptotrader.exchange.kraken_rest import KrakenRest


@pytest.mark.asyncio
async def test_place_order_returns_txid():
    client = KrakenRest("test_key", "dGVzdF9zZWNyZXQ=")  # base64-safe dummy secret
    with aioresponses() as m:
        m.post(
            "https://api.kraken.com/0/private/AddOrder",
            payload={"error": [], "result": {"txid": ["TXID-1234"]}},
        )
        txid = await client.place_order("XBTUSD", "buy", 0.001)
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
            await client.place_order("XBTUSD", "buy", 0.001)
    await client.close()
