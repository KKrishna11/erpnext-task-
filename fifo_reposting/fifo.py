"""FIFO layer queue (mirrors ERPNext's `stock_queue`: a list of [qty, rate])."""
from decimal import Decimal
from typing import Iterable, Tuple

Layer = Tuple[Decimal, Decimal]


class InsufficientStockError(Exception):
    pass


class FIFOQueue:
    def __init__(self, layers: Iterable[Layer] = ()):
        self._layers = [[Decimal(q), Decimal(r)] for q, r in layers]

    @property
    def qty(self) -> Decimal:
        return sum((q for q, _ in self._layers), Decimal(0))

    @property
    def value(self) -> Decimal:
        return sum((q * r for q, r in self._layers), Decimal(0))

    def add(self, qty: Decimal, rate: Decimal) -> None:
        self._layers.append([Decimal(qty), Decimal(rate)])

    def consume(self, qty: Decimal) -> Decimal:
        """Remove `qty` from the oldest layers; return the total value consumed."""
        qty = Decimal(qty)
        if qty > self.qty:
            raise InsufficientStockError(f"need {qty}, have {self.qty}")
        value, remaining = Decimal(0), qty
        while remaining > 0:
            layer = self._layers[0]
            take = min(layer[0], remaining)
            value += take * layer[1]
            layer[0] -= take
            remaining -= take
            if layer[0] == 0:
                self._layers.pop(0)
        return value

    def snapshot(self) -> Tuple[Layer, ...]:
        return tuple((q, r) for q, r in self._layers)
