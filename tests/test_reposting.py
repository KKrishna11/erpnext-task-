from datetime import datetime
from decimal import Decimal as D
import pytest
from fifo_reposting import InsufficientStockError, Voucher, VoucherLine as L
from fifo_reposting.scenario import build_scenario, W


def vd(led, vno, item):
    return led.entry(vno, item).stock_value_difference


def test_baseline_valuation():
    led = build_scenario()
    assert vd(led, "DN-MILK-1", "Milk") == D(-4000)          # 80 x 50
    assert vd(led, "MFG-1", "Milk") == D(-5800)              # 20@50 + 50@60 + 30@60
    assert vd(led, "MFG-1", "Milk Powder") == D(5800)        # 580/kg
    assert vd(led, "DN-POWDER-1", "Milk Powder") == D(-5800)


def test_amend_purchase_rate_reprices_downstream():
    led = build_scenario()
    led.amend_rate("PR-1", 0, D(80))
    assert vd(led, "PR-1", "Milk") == D(4000)
    assert vd(led, "DN-MILK-1", "Milk") == D(-4000)          # untouched layer -> same value
    assert vd(led, "PR-2", "Milk") == D(3000)
    assert vd(led, "MFG-1", "Milk") == D(-6800)              # 20@50 + 50@80 + 30@60
    assert vd(led, "MFG-1", "Milk Powder") == D(6800)        # cascades to the FG
    assert vd(led, "DN-POWDER-1", "Milk Powder") == D(-6800)  # COGS changes
    assert led.entries("Milk")[-1].stock_queue == ((D(20), D(60)),)   # closing stock unaffected


def test_change_report_contains_only_affected_entries():
    led = build_scenario()
    changes = {(c.voucher_no, c.item): c for c in led.amend_rate("PR-1", 0, D(80))}
    assert set(changes) == {("PR-1", "Milk"), ("DN-MILK-1", "Milk"), ("PR-2", "Milk"),
                            ("MFG-1", "Milk"), ("MFG-1", "Milk Powder"), ("DN-POWDER-1", "Milk Powder")}
    # DN-MILK-1 / PR-2: value_diff same, only the running balance moved
    assert changes[("DN-MILK-1", "Milk")].old_value_diff == changes[("DN-MILK-1", "Milk")].new_value_diff
    assert changes[("DN-MILK-1", "Milk")].new_stock_value == D(5000)
    assert changes[("PR-2", "Milk")].new_stock_value == D(8000)


def test_reposting_is_idempotent_and_reversible():
    led = build_scenario()
    original = led.entries()
    led.amend_rate("PR-1", 0, D(80))
    assert led.amend_rate("PR-1", 0, D(80)) == []             # no-op second time
    led.amend_rate("PR-1", 0, D(60))
    assert led.entries() == original


def test_backdated_delivery_shifts_fifo_layers():
    led = build_scenario()
    led.post(Voucher("Delivery Note", "DN-BACK", datetime(2026, 1, 12), (L("Milk", W, D(-20)),)))
    assert vd(led, "DN-BACK", "Milk") == D(-1000)
    assert vd(led, "MFG-1", "Milk") == D(-6000)              # only 60-rate layers are left
    assert vd(led, "DN-POWDER-1", "Milk Powder") == D(-6000)


def test_failed_repost_is_atomic():
    led = build_scenario()
    before = led.entries()
    with pytest.raises(InsufficientStockError):              # would starve the 15 Jan DN
        led.post(Voucher("Delivery Note", "DN-BAD", datetime(2026, 1, 12), (L("Milk", W, D(-100)),)))
    assert led.entries() == before
