# Sanji's Pump.fun Bot Sprint Bot

[![Pump.fun Bot Sprint](https://make.fun/badge/u-riidzhsn-pump-fun-bot-sprint-make-bot-and-win-cb203fed.svg)](https://make.fun/bounty/u-riidzhsn-pump-fun-bot-sprint-make-bot-and-win-cb203fed)
[![Rank](https://make.fun/badge/u-riidzhsn-pump-fun-bot-sprint-make-bot-and-win-cb203fed/yofanprayoga/sanji-pumpfun-bot-sprint/rank.svg)](https://make.fun/bounty/u-riidzhsn-pump-fun-bot-sprint-make-bot-and-win-cb203fed)
[![Reward](https://make.fun/badge/u-riidzhsn-pump-fun-bot-sprint-make-bot-and-win-cb203fed/yofanprayoga/sanji-pumpfun-bot-sprint/reward.svg)](https://make.fun/bounty/u-riidzhsn-pump-fun-bot-sprint-make-bot-and-win-cb203fed)

Entry for make.fun's [Pump.fun Bot Sprint: Make Bot And Win](https://make.fun/bounty/u-riidzhsn-pump-fun-bot-sprint-make-bot-and-win-cb203fed): a Solana trading bot that trades paper money on a replay of pump.fun chain data (agent-fun/replay/v2), scored by net PnL.

## Strategy

Deterministic, integer math only, no floats, no clock, no randomness, no network:

- Watch each new coin from its CreateEvent; buy once per coin, 0.05 SOL, only when the early tape shows strong real demand: at least 8 buy trades from at least 8 different wallets, at least 8 SOL of net inflow, price at least 30% above the create price, creator has not sold, real SOL reserves between 0.5 and 80 SOL.
- Sell the whole position at +10% take-profit, -10% stop-loss, after 1200 slots held, or after 600 slots with no trade.
- At most 5 open positions, at most 16 orders per batch, no shorts.

## Honest note

On the frozen dev window (src-calib, 128,058 events) this strategy grades at roughly -0.36 SOL after all fees with the kit's own local grader — no profit is guaranteed. The final is 6 hours of fresh chain data, so the entry is a shot at a positive run, not a promised win.

## Run it

```sh
python3 main.py
```

`vendor/makefun_bot.py` is the kit's SDK shim, copied unchanged.
