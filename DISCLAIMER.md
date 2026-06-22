# Disclaimer

CryptoTrader is experimental algorithmic trading software. Please read this before running it in
production mode.

## Real money, real risk

In `production` mode this software connects to a live Kraken account via your API keys and places
real buy and sell orders automatically, without per-trade confirmation. **You can lose some or all
of your funds.** Cryptocurrency prices are highly volatile; automated strategies can and do lose
money, especially in adverse or unusual market conditions.

## No warranty

This software is provided "AS IS", without warranty of any kind, express or implied, as stated in
the project [LICENSE](LICENSE). It may contain bugs and may place incorrect, mistimed, duplicate,
or missed orders. Exchange outages, network failures, stale market data, and misconfiguration can
all cause financial loss. The authors and contributors accept no liability for any loss or damage
arising from the use of this software.

## Not financial advice

Nothing in this repository — including the code, comments, configuration defaults, documentation,
or any backtest/analysis results — constitutes investment, financial, legal, or tax advice.
Backtests and historical results are not indicative of future performance.

## Your responsibility

You are solely responsible for:

- securing and scoping your Kraken API keys (grant the minimum permissions necessary);
- the funds in any account you connect;
- your strategy selection, parameters, and risk settings (including stop-loss configuration);
- monitoring the bot's behaviour; and
- complying with all laws, regulations, and exchange terms of service that apply to you.

## Before trading real money

- Run in `test` (paper-trading) mode first and review the strategy logic and configuration.
- Trade only with capital you can afford to lose entirely.

By running this software in production mode, you acknowledge and accept these terms and assume full
responsibility for all trades and outcomes.
