"""Errors raised while loading and validating structure profiles."""

from __future__ import annotations

from collections.abc import Sequence


class ProfileError(ValueError):
    """A structure profile failed validation.

    Carries every problem found, not just the first, so a model or a person
    fixing a hand-written profile can address them in one pass.
    """

    def __init__(self, errors: Sequence[str]):
        self.errors = list(errors)
        detail = "\n".join(f"  - {message}" for message in self.errors)
        super().__init__(f"Invalid structure profile:\n{detail}")
