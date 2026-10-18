"""The renderers over a `redlines.comparison.Comparison` (ADR-0037, ADR-0038).

Every in-place output walks one view of the *test* document: its blocks in
pre-order, with the source blocks of deletions and the origins of moves placed
where they stood (ADR-0033's anchor). The machinery lives in private modules,
because the `redlines.comparison.Comparison` methods are the API and pdoc
publishes every public module:

- ``_marks``: what each output spells for an insert, a delete, a replacement
  and a note (`MarkSet`);
- ``_escape``: the CriticMarkup escape, role encoding, and the HTML escapers;
- ``_view``: the view itself;
- ``_inplace``: the inline splice, the line syntax and the in-place traversal;
- ``_rich``: the rich renderer, the only module here that imports rich.

The 0.6 rendering loops stay in `redlines.redlines`, untouched: a renderer over
a block tree cannot be byte-identical to them (ADR-0036), so these are new
renderers with goldens of their own.

Nothing here is public yet. The HTML renderer adds this package's two public
names, the fragment version and the stylesheet.
"""

from __future__ import annotations

__all__: tuple[str, ...] = ()
