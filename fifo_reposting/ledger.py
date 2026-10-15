"""Stock ledger + FIFO reposting engine.

Core idea
---------
Vouchers are the source of truth; Stock Ledger Entries (SLEs) are derived.
When a voucher is amended / back-dated, we mark (item, warehouse) as *dirty*
from that voucher's position onward, rebuild the FIFO queue from the last
untouched SLE snapshot, and replay vouchers in (posting_dt, creation) order.

Dirtiness cascades: if a dirty consumption line sits in a Manufacture voucher,
the finished-good key becomes dirty from that voucher, so downstream sales of
the finished good are revalued too. The whole repost runs on a working copy and
is committed atomically (a failure such as negative stock changes nothing).
"""
from dataclasses import replace
from decimal import Decimal
from typing import Dict, List, Tuple

from .fifo import FIFOQueue
from .models import Change, StockLedgerEntry, Voucher

Key = Tuple[str, str]


class StockLedger:
    def __init__(self):
        self._vouchers: Dict[str, Voucher] = {}
        self._sles: Dict[Tuple[str, int], StockLedgerEntry] = {}

    # ---------------------------------------------------------------- public
    def post(self, voucher: Voucher) -> List[Change]:
        """Post a voucher (also works back-dated)."""
        if voucher.name in self._vouchers:
            raise ValueError(f"{voucher.name} already exists")
        vouchers = {**self._vouchers, voucher.name: voucher}
        dirty = {l.key: voucher.sort_key for l in voucher.lines}
        return self._commit(vouchers, dirty)

    def amend_rate(self, voucher_name: str, line_idx: int, new_rate) -> List[Change]:
        """Change the incoming rate of one line and reprice everything downstream."""
        v = self._vouchers[voucher_name]
        line = v.lines[line_idx]
        if line.qty <= 0 or line.rate is None:
            raise ValueError("only fixed-rate incoming lines can be amended")
        lines = list(v.lines)
        lines[line_idx] = replace(line, rate=Decimal(new_rate))
        vouchers = {**self._vouchers, voucher_name: replace(v, lines=tuple(lines))}
        return self._commit(vouchers, {line.key: v.sort_key})

    def entries(self, item: str = None, warehouse: str = None) -> List[StockLedgerEntry]:
        out = [s for s in self._sles.values()
               if (item is None or s.item == item) and (warehouse is None or s.warehouse == warehouse)]
        return sorted(out, key=lambda s: (s.sort_key, s.line_idx))

    def entry(self, voucher_no: str, item: str) -> StockLedgerEntry:
        return next(s for s in self.entries(item) if s.voucher_no == voucher_no)

    # -------------------------------------------------------------- internals
    def _commit(self, vouchers, dirty) -> List[Change]:
        new_sles = self._repost(vouchers, dirty)      # raises -> nothing committed
        changes = self._diff(self._sles, new_sles)
        self._vouchers, self._sles = vouchers, new_sles
        return changes

    def _repost(self, vouchers: Dict[str, Voucher], dirty: Dict[Key, tuple]):
        sles = dict(self._sles)                        # SLEs are frozen -> shallow copy is safe
        dirty = dict(dirty)
        queues: Dict[Key, FIFOQueue] = {}

        def start_queue(key: Key, frm: tuple) -> None:
            prior = [s for s in sles.values() if (s.item, s.warehouse) == key and s.sort_key < frm]
            last = max(prior, key=lambda s: (s.sort_key, s.line_idx), default=None)
            queues[key] = FIFOQueue(last.stock_queue if last else ())

        def is_dirty(key: Key, vk: tuple) -> bool:
            return key in dirty and vk >= dirty[key]

        def write(v: Voucher, idx: int, value_diff: Decimal) -> None:
            line, q = v.lines[idx], queues[v.lines[idx].key]
            sles[(v.name, idx)] = StockLedgerEntry(
                v.voucher_type, v.name, idx, line.item, line.warehouse, v.sort_key,
                line.qty, value_diff, q.qty, q.value,
                (q.value / q.qty) if q.qty else Decimal(0), q.snapshot())

        for key, frm in dirty.items():
            start_queue(key, frm)
        start = min(dirty.values())

        for v in sorted(vouchers.values(), key=lambda x: x.sort_key):
            vk = v.sort_key
            if vk < start:
                continue
            outs = [(i, l) for i, l in enumerate(v.lines) if l.qty < 0]
            ins = [(i, l) for i, l in enumerate(v.lines) if l.qty > 0 and l.rate is not None]
            fgs = [(i, l) for i, l in enumerate(v.lines) if l.qty > 0 and l.rate is None]

            consumed, any_out_dirty = Decimal(0), False
            for i, l in outs:
                if is_dirty(l.key, vk):
                    any_out_dirty = True
                    write(v, i, -queues[l.key].consume(-l.qty))
                consumed += -sles[(v.name, i)].stock_value_difference

            for i, l in ins:
                if is_dirty(l.key, vk):
                    queues[l.key].add(l.qty, l.rate)
                    write(v, i, l.qty * l.rate)

            fg_qty = sum((l.qty for _, l in fgs), Decimal(0))
            for i, l in fgs:
                if any_out_dirty and l.key not in dirty:   # cascade to the produced item
                    dirty[l.key] = vk
                    start_queue(l.key, vk)
                if is_dirty(l.key, vk):
                    rate = consumed / fg_qty
                    queues[l.key].add(l.qty, rate)
                    write(v, i, l.qty * rate)
        return sles

    @staticmethod
    def _diff(old, new) -> List[Change]:
        out = []
        for k, n in new.items():
            o = old.get(k)
            if o is None or o.stock_value_difference != n.stock_value_difference or o.stock_value != n.stock_value:
                out.append((n.sort_key, n.line_idx, Change(
                    n.voucher_no, n.item,
                    o.stock_value_difference if o else None, n.stock_value_difference,
                    o.stock_value if o else None, n.stock_value)))
        return [c for _, _, c in sorted(out, key=lambda t: (t[0], t[1]))]
