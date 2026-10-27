def add(a: int, b: int) -> int:
    """Return the sum of two integers."""
    return a + b


def subtract(a: int, b: int) -> int:
    """Return the difference of two integers."""
    return a - b


def multiply(a: int, b: int) -> int:
    """Return the product of two integers."""
    return a * b


def is_positive(number: int) -> bool:
    """Return whether number is greater than zero."""
    return number > 0


def is_even(number: int) -> bool:
    """Return whether number is even."""
    return number % 2 == 0


def is_odd(number: int) -> bool:
    """Return whether number is odd."""
    return number % 2 != 0


def is_divisible_by_five(number: int) -> bool:
    """Return whether number is divisible by 5."""
    return number % 5 == 0
