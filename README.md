# FIFO Stock Reposting (ERPNext-style)

A small, dependency-free Python model of how ERPNext should **repost item valuation under FIFO**
when a past transaction is edited or back-dated, including cascades through a Manufacture entry.

```bash
python -m pytest -q                 # 8 tests
PYTHONPATH=. python examples/demo.py
```

## The scenario

| Date   | Voucher                    | Effect (before edit)                       |
|--------|----------------------------|--------------------------------------------|
| 1 Jan  | Opening                    | 100 L @ 50                                 |
| 10 Jan | PR-1                       | +50 L @ **60 → edited to 80**              |
| 15 Jan | DN Milk 80 L               | consumes 80 @ 50 = 4,000                   |
| 20 Jan | PR-2                       | +50 L @ 60                                 |
| 21 Jan | Manufacture                | −100 L Milk, +10 kg Milk Powder            |
| 25 Jan | DN Milk Powder 10 kg       | outgoing                                   |

| Entry                      | Before | After  |
|----------------------------|-------:|-------:|
| PR-1 value                 | 3,000  | 4,000  |
| DN 15 Jan (value)          | 4,000  | 4,000 (balance moves 4,000 → 5,000) |
| PR-2 value                 | 3,000  | 3,000 (balance moves 7,000 → 8,000) |
| Manufacture – Milk consumed| 5,800  | **6,800** (20@50 + 50@80 + 30@60) |
| Milk Powder rate           | 580/kg | **680/kg** |
| DN 25 Jan – Milk Powder    | 5,800  | **6,800** (COGS changes) |
| Closing Milk               | 20 @ 60 | 20 @ 60 (unchanged) |

## 1. Which transactions are affected?

* **Same item (Milk, same warehouse), everything from 10 Jan onward** must be *re-evaluated*, because FIFO
  layer consumption depends on the layers before it. Not everything *changes value*:
  the 15 Jan DN draws only from the ₹50 layer, so its value is unchanged (only its running balance changes).
* **Value actually changes:** PR-1, the Manufacture entry (consumption), and its finished good.
* **Cascade to another item:** Milk Powder's incoming rate is derived from the Milk consumed, so
  the 25 Jan Milk Powder DN is revalued too (and so is its COGS in the General Ledger).
* **Side effects beyond the Stock Ledger:** GL entries (Stock In Hand / COGS / Stock Adjustment) of every voucher whose
  value changed, plus Bin (`valuation_rate`, `stock_value`) for both items.

## 2. How should the recalculation work?

Replay in strict chronological order, `(posting_datetime, creation)`:

1. Take the FIFO queue from the **last unaffected SLE** before the edited voucher.
2. Re-apply every later movement: receipts push a layer, issues pop from the oldest layer and compute the outgoing value.
3. Manufacture: value of consumed raw material ÷ produced qty = FG incoming rate.
4. Update each SLE (`stock_value_difference`, `qty_after_transaction`, `stock_value`, `valuation_rate`, queue snapshot).
5. Regenerate GL entries for vouchers whose value moved.

## 3. Reposting design

Vouchers are the source of truth, SLEs are derived. See `fifo_reposting/ledger.py`.

* A **dirty map** `{(item, warehouse): from_position}` says where recomputation must begin per key.
* Walk vouchers after the earliest dirty position; only lines whose key is dirty at that point are recomputed,
  everything else is read as-is.
* **Cascade rule:** if a dirty *consumption* line is in a voucher that produces another item, that item becomes
  dirty from that voucher → downstream sales of the FG are repriced. This also handles multi-level BOMs
  because the cascade happens during the same ordered walk.
* **Atomic:** the repost runs on a working copy and commits only on success (e.g. negative stock raises
  `InsufficientStockError`, ledger untouched).
* **Idempotent:** reposting twice or reverting the rate restores identical entries (tested).
* Production notes: run as a background job per item/warehouse under a lock (ERPNext: `Repost Item Valuation`
  / `update_entries_after`), an early exit when recomputed SLEs equal the old ones and no downstream key is dirty, and
  index SLEs by `(item, warehouse, posting_datetime)`.

## 4. Problems with a running balance stored in every SLE

* **Back-dated / edited entries invalidate every later row** → O(n) rewrite of all subsequent SLEs.
* **Concurrency:** two simultaneous postings read the same "previous balance" and both write a stale one → needs row/queue locks, which serialise writes per item.
* **Partial failure / crash mid-repost** leaves a ledger where some rows are old and others new (hence atomic commit).
* **FIFO needs more than a number:** a balance qty/value is not enough; the layer queue (`stock_queue`) must also be stored and kept in sync, which is bulky for items with many layers.
* **Drift & rounding:** accumulated float/rounding errors; balances stop matching GL and Bin.
* **Ordering ambiguity** for same-timestamp entries if the tie-breaker isn't deterministic.
* **Cascades** across items (manufacturing) aren't visible from one item's balance chain.
* **Mitigations:** derive from vouchers, `Decimal` arithmetic, deterministic ordering, locks, repost queue, reconciliation checks (sum of `stock_value_difference` == final `stock_value`).

## Layout

```
fifo_reposting/fifo.py      FIFO layer queue
fifo_reposting/models.py    Voucher, VoucherLine, StockLedgerEntry, Change
fifo_reposting/ledger.py    Ledger + reposting engine
fifo_reposting/scenario.py  The assignment scenario
tests/                      pytest suite (8 tests)
examples/demo.py            Prints the before/after diff
```

## Known simplifications

Single currency, no landed cost, no serial/batch, FG rate = total consumed value ÷ FG qty (no operation/overhead cost),
no negative-stock mode, in-memory storage.
