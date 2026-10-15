from decimal import Decimal as D
import pytest
from fifo_reposting import FIFOQueue, InsufficientStockError


def test_consume_spans_layers():
    q = FIFOQueue([(D(20), D(50)), (D(50), D(60))])
    assert q.consume(D(30)) == D(20 * 50 + 10 * 60)
    assert q.snapshot() == ((D(40), D(60)),)


def test_insufficient_stock():
    with pytest.raises(InsufficientStockError):
        FIFOQueue([(D(5), D(1))]).consume(D(6))
