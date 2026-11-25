"""Pump.fun Bot Sprint entry: a paper trading bot on agent-fun/replay/v2.

The bot is plain Python 3.13 stdlib. It never touches the network, the clock,
or anything random, and every number it uses is an integer count of lamports
or reserves, so running it twice over the same replay gives the same replies.

What it does, in short. Each mint gets a little notebook that starts at its
CreateEvent and collects the first trades. The bot buys a mint once, for
0.05 SOL, only when the notebook shows real, broad demand: eight or more buy
trades from eight or more different wallets, eight or more SOL of net inflow,
a price thirty percent or more above the create price, a creator who has not
sold anything, and real SOL reserves between half a SOL and eighty SOL. The
bar is set that high on purpose: looser versions of this same idea traded
438 and 342 coins on the dev window and lost more, while this one trades 252
and keeps the fee drag smaller. The final is six hours of fresh chain
data, so the filter is tuned for robustness rather than for the dev
window's own quirks.

It exits a position in full when the position is up ten percent, down ten
percent, held for 1200 slots, or quiet for 600 slots. It never shorts, never
leverages, never holds more than five positions, and never sends more than
sixteen orders in one batch.

The hello message hands over the paper capital and the caps; every batch
brings events, marks, fills and the account at its slot; every reply echoes
the batch sequence number with the orders for that batch.
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "vendor"))

import makefun_bot  # noqa: E402

SOL = makefun_bot.LAMPORTS_PER_SOL
BUY_SIZE_LAMPORTS = SOL // 20              # 0.05 SOL into one mint
MIN_ROUNDTRIP_LAMPORTS = SOL // 100        # 0.01 SOL, the round-trip floor
RESERVE_FLOOR = SOL // 2                   # 0.5 SOL of real reserves
RESERVE_CEIL = SOL * 80                    # 80 SOL of real reserves
MIN_TAPE_AGE_SLOTS = 5                     # slots after the create
MIN_BUY_TRADES = 8
MIN_BUYERS = 8
MIN_NET_FLOW = SOL * 8                     # at least 8 SOL net inflow
MIN_RISE_BPS = 3000                        # price 30% above the create price
BUY_SLIPPAGE_BPS = 1500
SELL_SLIPPAGE_BPS = 10000
TAKE_PROFIT_BPS = 11000                    # exit once value is 110% of cost
STOP_LOSS_BPS = 9000                       # exit once value is 90% of cost
MAX_HOLD_SLOTS = 1200
MAX_STALE_SLOTS = 600


class Tape:
    """The early notebook of one mint, built up from batch events in order."""

    __slots__ = (
        "created_slot", "base_quote", "base_tokens", "net_flow",
        "buys", "buyers", "creator", "creator_sold", "seen_slot",
    )

    def __init__(self, created_slot, base_quote, base_tokens, creator):
        self.created_slot = created_slot
        self.base_quote = base_quote
        self.base_tokens = base_tokens
        self.net_flow = 0
        self.buys = 0
        self.buyers = set()
        self.creator = creator
        self.creator_sold = False
        self.seen_slot = created_slot


tapes = {}
done = set()
held_since = {}


def has_risen(curve, tape):
    """True when the price sits at least MIN_RISE_BPS above the create price.

    The comparison is integer cross-multiplication, so no float is ever
    involved: quote_now * tokens_create * 10000 has to reach at least
    quote_create * tokens_now * (10000 + MIN_RISE_BPS).
    """
    if tape.base_tokens == 0 or curve.virtual_token_reserves == 0:
        return False
    left = curve.virtual_quote_reserves * tape.base_tokens * 10000
    right = tape.base_quote * curve.virtual_token_reserves * (10000 + MIN_RISE_BPS)
    return left >= right


def quote_value(tokens, curve):
    """What a token holding is worth at the current reserves, integer only."""
    if curve.virtual_token_reserves == 0:
        return 0
    return tokens * curve.virtual_quote_reserves // curve.virtual_token_reserves


def ingest_events(batch):
    """Fold one batch of events into the notebooks, in stream order."""
    for event in batch["events"]:
        mint = event["mint"]
        kind = event["event"]
        if kind == "CreateEvent":
            if mint not in tapes:
                tapes[mint] = Tape(
                    event["slot"],
                    int(event["virtual_quote_reserves"]),
                    int(event["virtual_token_reserves"]),
                    event["creator"],
                )
        elif kind == "TradeEvent":
            tape = tapes.get(mint)
            if tape is None:
                tape = Tape(
                    event["slot"],
                    int(event["virtual_quote_reserves"]),
                    int(event["virtual_token_reserves"]),
                    event["creator"],
                )
                tapes[mint] = tape
            sol = int(event["sol_amount"])
            if event["is_buy"]:
                tape.net_flow += sol
                tape.buys += 1
                tape.buyers.add(event["user"])
            else:
                tape.net_flow -= sol
                if event["user"] == tape.creator:
                    tape.creator_sold = True
            tape.seen_slot = event["slot"]
        elif kind == "CompleteEvent":
            done.add(mint)


def exit_now(value, cost, held_for, stale_for):
    """A single place for all four exit reasons: up enough, down enough,
    held too long, or gone quiet for too long."""
    return (
        value * 10000 >= cost * TAKE_PROFIT_BPS
        or value * 10000 <= cost * STOP_LOSS_BPS
        or held_for >= MAX_HOLD_SLOTS
        or stale_for >= MAX_STALE_SLOTS
    )


def plan_exits(state, slot):
    """Work out the sells first, so a slot freed by an exit is only reused
    once that exit's fill has actually landed. Returns the sell orders."""
    for mint in state.positions:
        if mint not in held_since:
            held_since[mint] = slot
    # Drop the clocks of positions that are gone, so stale entries cannot
    # leak into a later decision about a mint that gets bought again.
    for mint in list(held_since):
        if mint not in state.positions:
            del held_since[mint]
    orders = []
    for mint, holding in list(state.positions.items()):
        curve = state.curves.get(mint)
        if curve is None or curve.complete:
            continue
        cost = holding.cost_lamports
        if cost <= 0 or holding.token_amount <= 0:
            continue
        value = quote_value(holding.token_amount, curve)
        held_for = slot - held_since.get(mint, slot)
        if mint in tapes:
            stale_for = slot - tapes[mint].seen_slot
        else:
            stale_for = 0
        if exit_now(value, cost, held_for, stale_for):
            orders.append({
                "side": "sell", "mint": mint,
                "token_amount": holding.token_amount,
                "max_slippage_bps": SELL_SLIPPAGE_BPS,
            })
    return orders


def entry_ok(tape, curve, slot):
    """A single place for the whole buy gate: the notebook is old enough,
    enough distinct buyers and inflow are on the tape, the price has risen,
    the creator is still holding, and the reserves are inside the band."""
    if slot - tape.created_slot < MIN_TAPE_AGE_SLOTS:
        return False
    if tape.buys < MIN_BUY_TRADES or len(tape.buyers) < MIN_BUYERS:
        return False
    if tape.net_flow < MIN_NET_FLOW or tape.creator_sold:
        return False
    if not has_risen(curve, tape):
        return False
    real_sol = curve.real_quote_reserves
    return RESERVE_FLOOR <= real_sol <= RESERVE_CEIL


def plan_entries(state, batch, slot, orders):
    """Work out the buys, one per mint, walking the batch events in order.
    The sell orders already planned are passed in and extended in place."""
    fee = state.tx_fee_lamports()
    cash = state.free_cash_lamports()
    for already in orders:
        cash -= fee  # every order, sells included, pays the transaction fee
    open_slots = state.hello["caps"]["max_open_positions"] - state.committed_position_count()
    for event in batch["events"]:
        if len(orders) >= state.hello["caps"]["max_orders_per_batch"] or open_slots <= 0:
            break
        mint = event["mint"]
        if mint in done:
            continue
        tape = tapes.get(mint)
        curve = state.curves.get(mint)
        if tape is None or curve is None or curve.complete:
            continue
        if not entry_ok(tape, curve, slot):
            continue
        cap = state.max_buy_lamports(mint)
        if cap < MIN_ROUNDTRIP_LAMPORTS:
            continue
        # One buy per mint: close the notebook off before sizing, so no
        # later event in this same batch can buy the mint a second time.
        done.add(mint)
        amount = cap if cap < BUY_SIZE_LAMPORTS else BUY_SIZE_LAMPORTS
        if cash < amount + fee:
            continue
        orders.append({
            "side": "buy", "mint": mint,
            "quote_lamports": amount,
            "max_slippage_bps": BUY_SLIPPAGE_BPS,
        })
        cash -= amount + fee
        open_slots -= 1


def handle_batch(state, batch):
    slot = batch["slot"]
    ingest_events(batch)
    orders = plan_exits(state, slot)
    plan_entries(state, batch, slot, orders)
    return orders


def on_hello(state):
    return None


def on_done(state, done):
    return None


if __name__ == "__main__":
    makefun_bot.run(handle_batch, on_hello=on_hello, on_done=on_done)
