class PlanError(Exception):
    """Invalid plan, override or query argument."""


class RuleSyntaxError(PlanError):
    """Invalid rule text."""

    def __init__(self, message, position, *, text=None):
        super().__init__(message)
        self.position = position
        self.text = text


def describe_value(value):
    """Describe a field that should be a string without formatting arbitrary objects."""
    return repr(value) if isinstance(value, str) else f"<{type(value).__name__}>"
