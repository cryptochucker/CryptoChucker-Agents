import pytest
from utils.risk_manager import position_size, drawdown_breached


def test_position_size():
    # risk $100 (1% of 10k), entry 100 stop 95 -> size = 100/5 = 20 units
    assert position_size(10000, 0.01, entry=100, stop=95) == pytest.approx(20.0)


def test_drawdown_breached():
    assert drawdown_breached([100, 120, 90], max_dd_pct=0.2) is True   # 25% from peak 120
    assert drawdown_breached([100, 110, 105], max_dd_pct=0.2) is False
