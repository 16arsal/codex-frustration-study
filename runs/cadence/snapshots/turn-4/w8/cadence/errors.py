class PlanError(Exception):
    """Invalid plan, override or query argument."""


class RuleSyntaxError(PlanError):
    """Invalid rule text."""

    def __init__(self, message, position, text=None):
        super().__init__(message)
        self.position = position
        self.text = text


def describe_value(value):
    """Describe an invalid field without formatting arbitrarily large numbers or containers."""
    if isinstance(value, str):
        return repr(value)
    return f"<{type(value).__name__}>"
