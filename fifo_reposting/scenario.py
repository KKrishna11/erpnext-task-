"""The exact scenario from the assignment (year 2026)."""
from datetime import datetime
from decimal import Decimal as D

from .ledger import StockLedger
from .models import Voucher, VoucherLine as L

W = "Stores"


def build_scenario() -> StockLedger:
    led = StockLedger()
    led.post(Voucher("Stock Reconciliation", "OPEN-1", datetime(2026, 1, 1), (L("Milk", W, D(100), D(50)),)))
    led.post(Voucher("Purchase Receipt", "PR-1", datetime(2026, 1, 10), (L("Milk", W, D(50), D(60)),)))
    led.post(Voucher("Delivery Note", "DN-MILK-1", datetime(2026, 1, 15), (L("Milk", W, D(-80)),)))
    led.post(Voucher("Purchase Receipt", "PR-2", datetime(2026, 1, 20), (L("Milk", W, D(50), D(60)),)))
    led.post(Voucher("Stock Entry", "MFG-1", datetime(2026, 1, 21),
                     (L("Milk", W, D(-100)), L("Milk Powder", W, D(10)))))
    led.post(Voucher("Delivery Note", "DN-POWDER-1", datetime(2026, 1, 25), (L("Milk Powder", W, D(-10)),)))
    return led
