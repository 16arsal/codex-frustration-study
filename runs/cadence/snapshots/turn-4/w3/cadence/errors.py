class PlanError(Exception):
    """Invalid plan, override or query argument."""


class RuleSyntaxError(PlanError):
    """Invalid rule text."""

    def __init__(self, message, position, text=None):
        super().__init__(message)
        self.position = position
        self.text = text
