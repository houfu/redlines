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
- ``_html``: the two HTML fragments, the change list and the document view
  (ADR-0038).

The 0.6 rendering loops stay in `redlines.redlines`, untouched: a renderer over
a block tree cannot be byte-identical to them (ADR-0036), so these are new
renderers with goldens of their own.

The package has two public names, for a shell that injects the HTML
fragments (ADR-0038): `FRAGMENT_VERSION`, the version of the contract the
fragments meet, and `STYLESHEET`, the content of their one ``<style>``, which a
shell can carry in its own document instead if a host blocks an injected
``<style>``, or hash for a content security policy.
"""

from __future__ import annotations

from ._html import FRAGMENT_VERSION, STYLESHEET

__all__: tuple[str, ...] = ("FRAGMENT_VERSION", "STYLESHEET")
