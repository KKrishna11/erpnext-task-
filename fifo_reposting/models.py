from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from itertools import count
from typing import Optional, Tuple

_creation = count(1)


@dataclass(frozen=True)
class VoucherLine:
    """One stock movement.

    qty < 0                  -> outgoing (valued from FIFO layers)
    qty > 0 and rate set     -> incoming at a known rate (Purchase Receipt, Opening)
    qty > 0 and rate is None -> finished good of a Manufacture entry; its rate is
                                derived from the value of everything consumed in
                                the same voucher.
    """
    item: str
    warehouse: str
    qty: Decimal
    rate: Optional[Decimal] = None

    @property
    def key(self) -> Tuple[str, str]:
        return (self.item, self.warehouse)


@dataclass(frozen=True)
class Voucher:
    voucher_type: str
    name: str
    posting_dt: datetime
    lines: Tuple[VoucherLine, ...]
    creation: int = field(default_factory=lambda: next(_creation))

    @property
    def sort_key(self):
        # posting datetime first, creation order as the tie-breaker (like ERPNext)
        return (self.posting_dt, self.creation)


@dataclass(frozen=True)
class StockLedgerEntry:
    voucher_type: str
    voucher_no: str
    line_idx: int
    item: str
    warehouse: str
    sort_key: tuple
    actual_qty: Decimal
    stock_value_difference: Decimal
    qty_after_transaction: Decimal
    stock_value: Decimal
    valuation_rate: Decimal
    stock_queue: tuple  # FIFO layers *after* this entry (snapshot)


@dataclass(frozen=True)
class Change:
    voucher_no: str
    item: str
    old_value_diff: Optional[Decimal]
    new_value_diff: Decimal
    old_stock_value: Optional[Decimal]
    new_stock_value: Decimal
