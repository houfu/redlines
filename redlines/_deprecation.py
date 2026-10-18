"""The deprecation mechanism: two warning categories and the function that raises them.

Redlines 1.0 ships this mechanism and **no runtime deprecation warning**. Nothing in
the package calls `warn_deprecated`, and `tests/test_deprecations.py` fails if
something does. R46 asks for deprecation warnings, not removals, wherever something
is superseded. The three names that will be deprecated (`Redlines.changes`,
`Redlines.redlines` and `Redlines.get_changes`) are superseded by
`Comparison.changes`, from `redlines.compare(...)`, which is block-addressed and
counts characters, not tokens: it is not a drop-in replacement. The agent guide still
teaches the old names, and most installs are a 2023 pin from the course environment,
whose notebooks would show a `DeprecationWarning` on the page the reader is copying
from. So 1.0 ships the machinery, a tripwire and a written schedule, and the warnings
follow once the successor is documented (ADR-0036; ADR-0003; decision D11 of the M3
plan).

The schedule:

* **1.0.** This module, the tripwire (`filterwarnings` in `pyproject.toml`) and the
  docstrings of the three names, which say that they are superseded and that nothing
  is deprecated or removed yet. No runtime warning.
* **1.1.** The three names warn with `RedlinesPendingDeprecationWarning`. Python
  hides that category by default (pytest shows it), so a notebook still shows nothing.
* **1.2.** The same names warn with `RedlinesDeprecationWarning`, which Python shows
  for code in `__main__`, and so in notebooks.
* **Not before 2.0.** Removal, and only by a decision of its own.

There are two categories, not one with a flag, so that someone can silence or
escalate each phase separately. Both are exported from `redlines`;
`warn_deprecated` is not, because it is for redlines' own code.

The tripwire. `pyproject.toml` turns both categories into errors under pytest, so a
warning wired in early, or one that a call chain raises by accident, fails the
suite instead of reaching a user. It names the two categories and never the bare
`DeprecationWarning`, which click 8.5 emits for itself. `tests/test_deprecations.py`
holds the promise that nothing warns in 1.0, and `tests/test_quick_path_is_silent.py`
holds it for everything that a 0.6 user copies, runs or types.

The call-chain trap, for 1.1. `Redlines.redlines` and `Redlines.get_changes` read
`self.changes`, `stats()` reads `self.changes`, `output_json()` calls `stats()`, and
the `stats`, `text` and `json` commands of the CLI call `stats()`. A warning placed
on `changes` would be raised by every one of them. Before the first call to
`warn_deprecated`, each public name has to wrap a private `_changes()`: the public
name warns and then returns `self._changes()`, and everything inside the package
(`stats()`, `output_json()`, the CLI, the facade) calls `_changes()` and never a
public name. `stats()` and `output_json()` then stay silent (R30).

Also for 1.1: the unmodified 0.6 tests call the three names about 49 times, and they
may not be edited. Their warnings are silenced by message-scoped `ignore:` entries
added to `filterwarnings` *after* the two `error::` entries, because pytest applies
the last entry that matches.

On `stacklevel`. The default of 3 names the caller of the deprecated function: level
1 is `warn_deprecated`, level 2 the deprecated function, level 3 whoever called it.
A deprecated name that is reached through another redlines frame needs one level more
for each such frame, or the warning is attributed to redlines' own code and the user
cannot find the line to change. `tests/test_quick_path_is_silent.py` judges a warning
to be redlines' when its category is defined in the package, whichever file it names,
so a warning that is aimed at user code is still caught there.
"""

from __future__ import annotations

import warnings

__all__: tuple[str, ...] = (
    "RedlinesDeprecationWarning",
    "RedlinesPendingDeprecationWarning",
    "warn_deprecated",
)


class RedlinesPendingDeprecationWarning(PendingDeprecationWarning):
    """A name in redlines is superseded and is scheduled to be deprecated.

    This is the first phase of the schedule (ADR-0036): it is scheduled for redlines
    1.1, and no release before that raises it. Python ignores
    `PendingDeprecationWarning` by default, so it shows up in pytest, under
    `python -W default` and in development mode, but not in a notebook. To hide it,
    or to make it an error, filter on this class:

    ```python
    import warnings
    from redlines import RedlinesPendingDeprecationWarning

    warnings.filterwarnings("ignore", category=RedlinesPendingDeprecationWarning)
    ```
    """


class RedlinesDeprecationWarning(DeprecationWarning):
    """A name in redlines is deprecated. It is not removed before redlines 2.0.

    This is the second phase of the schedule (ADR-0036): it is scheduled for redlines
    1.2, and no release before that raises it. Python shows `DeprecationWarning` when
    it is attributed to code in `__main__`, which includes the cells of a notebook.
    To hide it, or to make it an error, filter on this class:

    ```python
    import warnings
    from redlines import RedlinesDeprecationWarning

    warnings.filterwarnings("error", category=RedlinesDeprecationWarning)
    ```
    """


def warn_deprecated(
    old: str,
    new: str,
    *,
    since: str,
    category: (
        type[RedlinesPendingDeprecationWarning] | type[RedlinesDeprecationWarning]
    ) = RedlinesPendingDeprecationWarning,
    stacklevel: int = 3,
) -> None:
    """Warn that `old` is deprecated in favour of `new`.

    The message is always `"{old} is deprecated since redlines {since}; use {new}
    instead."`: one line, with no removal date, because 1.0 promises none before 2.0.

    Nothing in redlines 1.0 calls this function. The module docstring has the schedule,
    and the rule that a public name must wrap a private implementation before it calls
    this.

    :param old: What is deprecated, as the user writes it, e.g. `"Redlines.changes"`.
    :param new: What to use instead, e.g. `"Comparison.changes"`.
    :param since: The release that began warning about `old`, e.g. `"1.1"`.
    :param category: `RedlinesPendingDeprecationWarning` in 1.1, the phase that
        pends, and `RedlinesDeprecationWarning` from 1.2. The type checker refuses any
        other category, because the tripwire only knows these two.
    :param stacklevel: Which frame the warning names, counted as for
        `warnings.warn`. The default of 3 is the caller of the function that called
        this one.
    """
    warnings.warn(
        f"{old} is deprecated since redlines {since}; use {new} instead.",
        category,
        stacklevel=stacklevel,
    )
