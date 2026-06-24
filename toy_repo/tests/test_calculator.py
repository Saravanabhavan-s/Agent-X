from __future__ import annotations

from calculator import add, divide, multiply, subtract


def test_add() -> None:
    assert add(2, 3) == 5


def test_subtract() -> None:
    assert subtract(10, 4) == 6


def test_multiply() -> None:
    # This test will FAIL until the agent fixes the off-by-one bug in multiply()
    assert multiply(3, 4) == 12


def test_divide() -> None:
    assert divide(10, 2) == 5.0


def test_divide_by_zero() -> None:
    import pytest
    with pytest.raises(ValueError, match="Cannot divide by zero"):
        divide(1, 0)
