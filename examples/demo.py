from decimal import Decimal
from fifo_reposting.scenario import build_scenario

led = build_scenario()
for c in led.amend_rate("PR-1", 0, Decimal(80)):
    print(f"{c.voucher_no:12} {c.item:12} value_diff {c.old_value_diff:>6} -> {c.new_value_diff:>6}"
          f" | balance {c.old_stock_value:>6} -> {c.new_stock_value:>6}")
