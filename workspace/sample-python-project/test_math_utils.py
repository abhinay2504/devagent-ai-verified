from math_utils import (
    add,
    subtract,
    multiply,
    is_positive,
    is_even,
    is_odd,
    is_divisible_by_five,
)


def test_add():
    assert add(2, 3) == 5
    assert add(-2, 3) == 1
    assert add(0, 0) == 0


def test_subtract():
    assert subtract(5, 3) == 2
    assert subtract(-2, 3) == -5
    assert subtract(0, 0) == 0


def test_multiply():
    assert multiply(2, 3) == 6
    assert multiply(-2, 3) == -6
    assert multiply(0, 3) == 0


def test_is_positive():
    assert is_positive(1) is True
    assert is_positive(0) is False
    assert is_positive(-1) is False


def test_is_even():
    assert is_even(2) is True
    assert is_even(4) is True
    assert is_even(-2) is True
    assert is_even(-4) is True
    assert is_even(0) is True


def test_is_odd():
    assert is_odd(1) is True
    assert is_odd(3) is True
    assert is_odd(-1) is True
    assert is_odd(-3) is True
    assert is_odd(0) is False


def test_is_divisible_by_five():
    assert is_divisible_by_five(10) is True
    assert is_divisible_by_five(15) is True
    assert is_divisible_by_five(7) is False
    assert is_divisible_by_five(-10) is True
    assert is_divisible_by_five(0) is True
