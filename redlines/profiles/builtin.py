"""The built-in structure profiles that ship in core: generic, contract, markdown.

These are the answer to "do I have to write a profile?" -- no: pick one of
these by name (PRD D30, ADR-0028). ``generic`` declares no structure at all,
``contract`` covers numbered commercial agreements in plain text, and
``markdown`` covers what is left of a markdown document once its syntax has
been stripped. ``legislation`` and auto-selection are 1.1 (PRD R1d).

Each profile is a commented YAML file next to this module, loaded through
`importlib.resources` so it works from a wheel, a zip or an editable
checkout, and validated by the same `parse_profile_yaml` a hand-written
profile goes through -- a built-in gets no privileged path.
"""

from __future__ import annotations

from functools import lru_cache
from importlib.resources import files

from .errors import ProfileError
from .loader import parse_profile_yaml
from .model import Profile

#: The built-in profiles, in the order they are documented: least
#: structured first. Every name here is also the stem of a ``.yaml`` file in
#: ``redlines/profiles/builtin/``.
BUILTIN_PROFILE_NAMES: tuple[str, ...] = ("generic", "contract", "markdown")

_BUILTIN_DIRECTORY = "builtin"


@lru_cache(maxsize=None)
def builtin_profile(name: str) -> Profile:
    """Return the built-in `Profile` called ``name``.

    :param name: One of `BUILTIN_PROFILE_NAMES` (``generic``, ``contract``
        or ``markdown``), matched exactly.
    :return: The validated profile. `Profile` and everything it holds is
        frozen, so the same object is shared by every caller and the result
        is cached rather than re-parsed per call.
    :raises ProfileError: If ``name`` is not a built-in profile. The message
        lists the names that are, since a caller reaching here has usually
        mistyped one or is passing a path that belongs in `load_profile`.
    """
    if name not in BUILTIN_PROFILE_NAMES:
        known = ", ".join(BUILTIN_PROFILE_NAMES)
        raise ProfileError(
            [
                f"{name!r}: unknown built-in profile (known: {known}). "
                "To load a profile of your own, use load_profile()."
            ]
        )
    resource = files(__package__) / _BUILTIN_DIRECTORY / f"{name}.yaml"
    return parse_profile_yaml(resource.read_text(encoding="utf-8"))
