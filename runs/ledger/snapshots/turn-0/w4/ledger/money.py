def parse_money(value):
    """Turn a money string such as "12.50" into cents."""
    return int(float(value) * 100)


def format_money(cents):
    return f"{cents / 100:.2f}"
