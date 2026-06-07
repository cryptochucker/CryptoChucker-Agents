import pytest
from utils.fees import fee


def test_taker_fee():
    assert fee(1000, "blofin", taker=True, table={"blofin": {"maker": 0.0002, "taker": 0.0006}}) == pytest.approx(0.6)


def test_unknown_exchange_uses_default():
    assert fee(1000, "unknown", taker=True, table={}) == pytest.approx(1.0)  # 0.001 default
