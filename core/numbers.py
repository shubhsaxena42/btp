"""Safe numeric parsing for form input (rejects NaN / infinity / garbage)."""
import math


def num(v, default=None):
    """Finite float from user input, else `default`."""
    try:
        f = float(str(v).strip().replace(',', ''))
    except (TypeError, ValueError):
        return default
    return f if math.isfinite(f) else default


def whole(v, default=None):
    """Integer value from user input (accepts '5' and '5.0'), else `default`."""
    f = num(v)
    if f is None or f != int(f):
        return default
    return int(f)
