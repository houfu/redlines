# ADR-0038: Render HTML once, in Python: one fragment contract

**Status:** Proposed
*Where the HTML is rendered is under research at the maintainer's request (18 October 2026); this ADR records the recommendation, Python, and its status changes to Accepted, or it is rewritten, with the pull request that implements the HTML renderer ([#182](https://github.com/houfu/redlines/issues/182)).*
**Date:** 2026-10-18
**Deciders:** houfu

## Context

R20 asks for an HTML renderer, and ROADMAP § 5.7 keeps it minimal: a block list plus expandable redlines, where "the site adds interaction on top rather than a second renderer". [ADR-0035](0035-hosted-demo-server.md) gave the same renderer a second consumer. In the hosted demo, the app-only `compare` sends "the full v2 document with both block trees" to the MCP App's iframe, and ROADMAP's M3 row said the view "takes its data by `postMessage`, supports fullscreen, and themes from the host's CSS variables". M6 then shows the same views in a Starlight page, from the wheel running in Pyodide ([ADR-0019](0019-client-side-demo-site.md), [ADR-0026](0026-docs-site-on-astro-starlight.md)).

That leaves one fork: render the HTML in Python and hand the shells a string, or render it in the iframe, in JavaScript, from the v2 JSON. Measured on the section 3a sample pair:

- the change-list fragment is 12,900 bytes (2,560 gzipped): 1,862 bytes of CSS, about 0.2 KB of header and about 1.05 KB per row;
- the document view is about 16,000 bytes;
- the full v2 document is 156,081 bytes with `to_json()`'s default separators.

So the two fragments add about 30 KB to an app-only result of about 156 KB, which never reaches the model. A renderer in the iframe would instead need the v2 document with `include_alignment=True`, about 17 KB more, because the document view places deletions from the alignment, which the full document omits by default; and it would need both trees for subtree emission. It would also be a second implementation and a second escaper. N7 says that no comparison logic lives outside the core library, and [ADR-0016](0016-summary-renderer-in-core.md) records the standing principle "that no comparison or rendering logic lives outside the core". CI is not the obstacle: the Pyodide job already runs Node, so a JavaScript renderer could be tested. That plays no part in this decision.

Two things about MCP App hosts are unknown until M5 runs in one: which CSS variables a host exposes, and whether a host's content security policy allows a `<style>` element that a script inserts.

## Decision

### Python renders, and the shells inject

- `Comparison.output_html()` and `Comparison.output_annotated(syntax="html")` are the only producers of change HTML in the project. `redlines-mcp` and `site/` inject them, and never render change data.
- The app-only `compare` result carries the full v2 document plus both strings, rendered from the same `Comparison`. M5 names the keys. The model-facing compact form is unchanged.
- The fragments are script-free, so injecting them is CSP-safe. The ROADMAP's earlier wording, "takes its data by `postMessage`", holds at the shell: the strings arrive by `postMessage`, inside the tool result.
- The contract below is versioned by `data-redlines-fragment="1.0"`. `redlines.renderers` exports `FRAGMENT_VERSION` and `STYLESHEET`.

| Milestone | Ships |
|---|---|
| M3 | the two fragment renderers; `STYLESHEET` and `FRAGMENT_VERSION`; checks F1 to F9 in `tests/helpers/fragment_checks.py`; the goldens |
| M5 | the static `ui://` shell, which injects both fragments; maps the host's CSS variables onto `--redlines-*`; un-hides the fullscreen button, wires it to `ui/request-display-mode` and then sets `data-redlines-display`; filters rows by their `data-*` attributes (F6); pushes `ui/update-model-context`; adds per-row actions and the intake drop zone; and carries `STYLESHEET` in its own static `ui://` document if a host blocks an injected `<style>` |
| M6 | an Astro island that gets the same two strings from Pyodide and injects them with the same few lines of shell code |

### The change list: `output_html()`

```html
<section class="redlines" data-redlines-view="changes" data-redlines-fragment="1.0" data-redlines-schema="2.0">
<style>STYLESHEET</style>
<header class="redlines-header">
<p class="redlines-counts"><span data-count="total">T change(s)</span><span data-count="insert">N inserted</span><span data-count="delete">N deleted</span><span data-count="modify">N modified</span><span data-count="move">N moved</span><span data-count="renumber">N renumbered</span></p>
<p class="redlines-config">FORMAT · profile PROFILE · similarity BACKEND</p>
<p class="redlines-structure">F of S source blocks and G of T test blocks matched no rule</p>
<p class="redlines-notice" data-notice="filtered">Filtered: FIELD=V,V; FIELD=V</p>
<p class="redlines-notice" data-notice="budget-exhausted">Alignment stopped early: the comparison budget ran out</p>
<p class="redlines-notice" data-notice="dropped" data-side="SIDE">COUNT KIND dropped from the SIDE: REASON</p>
<button type="button" class="redlines-fullscreen" data-redlines-action="fullscreen" hidden>Full screen</button>
</header>
<ol class="redlines-changes">ROWS</ol>
</section>
```

`data-redlines-schema` is the `SCHEMA_VERSION` the fragment was rendered from.

**Header.**

- **Counts** come from `comparison.statistics().counts`, which needs the statistics correction in [ADR-0033](0033-change-tree-wire-format.md)'s amendment of 18 October 2026.
- **Pluralisation.** The total reads "1 change" or "T changes"; the per-kind participles never change.
- **The configuration line.** `FORMAT` is `config.test_format`; `PROFILE` is `config.profile`, or `none` when it is empty; `BACKEND` is `config.similarity`.
- **The structure line.** `F` and `G` are each tree's `fallback_count`; `S` and `T` are `statistics().source_blocks` and `test_blocks`.
- **Notices** appear only when true, in this order:
  - filtered: the non-empty `ChangeFilter` fields, in declared order;
  - budget-exhausted;
  - one dropped notice per `Dropped`, source first.
- **No changes.** The `<ol>` is replaced by `<p class="redlines-empty">No changes.</p>`.

**Rows.**

- **Shape.** `<li class="redlines-change" ATTRS><details><summary>SUMMARY</summary><div class="redlines-inline">BODY</div></details></li>`, with no whitespace inside a row. Rows are joined by `\n`, in change-list order.
- **ATTRS,** in this order, each absent when its value is `None` or empty:
  - `data-index` (the position in `comparison.changes`), `data-kind`;
  - `data-address` (the test address; the source address on a delete);
  - `data-source-address`, `data-test-address`, `data-source-label`, `data-test-label`;
  - `data-block-kind`, `data-role`, `data-matched-by`;
  - `data-confidence` (`repr(round(confidence, 4))`), `data-chars` (`max(chars_added, chars_deleted)`);
  - `data-has-inline` (`true` or `false`, always present), `data-span-types` (sorted, space-separated).

  `data-address` is for display and scrolling only. A filter reads the two side-qualified addresses, because one string can name different blocks in the two trees: a deleted 2.2 and a 2.2 that moved in can share `/section[2]/list_item[2]`.
- **SUMMARY,** in this order:
  - `<span class="redlines-kind">KIND</span>`;
  - `<span class="redlines-label">LABEL</span>`: `OLD → NEW` when a move's or a renumber's labels differ, otherwise the test label (the source label on a delete); omitted when empty;
  - `<span class="redlines-excerpt">EXCERPT</span>`;
  - `<span class="redlines-breadcrumb">B1 › B2</span>`, omitted when empty;
  - `<span class="redlines-role">ROLE</span>`, omitted when `None`;
  - `<code class="redlines-address">ADDR</code>`, written `SRC → TEST` on a move;
  - `<span class="redlines-match">MATCHED_BY CONFIDENCE</span>`.
- **EXCERPT.**
  - Start from the test text, or the source text on a delete. For a block with empty text, join its subtree's text-bearing blocks and cells with ` | `.
  - `s = " ".join(text.split())`. If `len(s) <= 80`, the excerpt is `s`.
  - Otherwise `c = s.rfind(" ", 0, 81)`, and the excerpt is `(s[:c] if c > 0 else s[:80]) + "…"`.
- **BODY.**
  - The node's text with its inline ops spliced in the `html` set of [ADR-0037](0037-annotate-the-test-document.md).
  - An insert or delete instead shows its whole subtree under one `<ins>` or `<del>`: one line per text-bearing block, cells joined by ` | `, and move subtrees left out. The change list therefore reads both trees, as the document view does.
  - A move or renumber without inline ops shows its text with the label change.

### The document view: `output_annotated(syntax="html")`

This is the tag variant for HTML that [ADR-0011](0011-json-canonical-annotated-renderer.md) decided on, drawn by ADR-0037's walk.

- **Shell.** The same root, with `data-redlines-view="document"`, the same `<style>` and the same header. Then `<div class="redlines-document">` holds one element per entry of ADR-0037's view, in view order.
- **Blocks.**
  - `<p class="redlines-block" ATTRS>` holds the role span, the label span, the text and any note.
  - **Headings** add `role="heading" aria-level="L"`, with `L = attrs["atx_level"]` when present and `min(level + 1, 6)` otherwise, clamped to 1–6. Never `<h1>` to `<h6>`, so a host page's table of contents is untouched.
  - **ATTRS,** in order: `data-test-address` (absent on ghosts), `data-source-address` (on changed blocks with a source side, and on ghosts), `data-level` (`block.level`), `data-kind` (on changed blocks and ghosts), `data-role`.
- **Marks.**
  - Inserted and deleted blocks wrap label and text in `<ins>` or `<del>`.
  - A renumber is `<span class="redlines-label"><del>OLD</del><ins>NEW</ins></span>`.
  - A move destination carries `data-kind="move"` and ends with `<span class="redlines-note">moved from SRC_LABEL SRC_ADDRESS</span>`.
  - A tombstone is `<p class="redlines-note" data-kind="move" data-source-address="SRC" data-test-address="TEST">SRC_LABEL moved to TEST_LABEL TEST_ADDRESS</p>`.
- **Tables** are `<table class="redlines-table">`, with `<thead>` for the header row, marks per cell, and ghost rows placed as ADR-0037 places them.

### The contract

Both fragments meet it.

1. **One root element,** and no `id`s, so two fragments can share a page.
2. **Self-contained:**
   - exactly one `<style>`;
   - none of the elements `<script>`, `<link>`, `<img>`, `<iframe>`, `<object>`, `<embed>`, `<base>`, `<meta>`, `<form>`, `<svg>`, `<math>`;
   - none of the attributes `src`, `href`, `srcset`, `action`, `formaction`;
   - no `@import` and no `url(` in the CSS.
3. **CSP-safe:** no `on*` attributes and no `style=` attributes. All styling comes through classes and `[data-*]` selectors.
4. **Escaping:**
   - text goes through `html.escape(s, quote=False)`, and attribute values through `html.escape(s, quote=True)`, in double quotes;
   - every document-, profile- and engine-derived string passes through one of the two, labels, roles, addresses and `matched_by` included;
   - newlines are kept, and shown with `white-space: pre-wrap`.
5. **Theming:**
   - the stylesheet only reads `var(--redlines-NAME, FALLBACK)` and never declares a property, so a shell that sets `--redlines-*` on any ancestor wins by inheritance;
   - NAME is one of the twelve in the table after this list;
   - fallbacks use `light-dark()`, with `color-scheme: light dark` on `.redlines` (Chrome 123, Firefox 120, Safari 17.5). Where `light-dark()` is unsupported, the declaration falls back to inherited colours.
6. **Scoping:**
   - every selector in `STYLESHEET` starts with `.redlines`, as a compound or a descendant selector, and none is or contains `:root`, `html` or `body`;
   - an injected `<style>` is document-global, and M6 injects it into a Starlight page, where an `ins`, `del` or `p` selector would leak.
7. **Bidi isolation:**
   - `.redlines-block, .redlines-excerpt, .redlines-inline { unicode-bidi: isolate; }`, so direction controls in a document cannot reorder text outside their own block;
   - inside a block they still apply. That is a known limit.
8. **Interaction hooks:**
   - **fullscreen:** a hidden button with no handler. A shell un-hides it when the host offers a fullscreen display mode, listens by delegation (`closest('[data-redlines-action]')`), and sets `data-redlines-display="fullscreen"` on the root when the host reports the change; the stylesheet widens the layout under that selector;
   - **expand and collapse:** native `<details>`;
   - **extension:** a shell may append children to a row. Nothing in the stylesheet depends on the number of children.
9. **Versioning:** `data-redlines-fragment="1.0"`. Added attributes or classes bump the minor; a rename or a removal bumps the major.

The twelve theme properties of item 5:

| Property | Used for |
|---|---|
| `--redlines-font` | body font |
| `--redlines-mono` | addresses and scores |
| `--redlines-fg` | text |
| `--redlines-bg` | background |
| `--redlines-muted` | breadcrumb, role, metadata |
| `--redlines-border` | row rules |
| `--redlines-ins-fg`, `--redlines-ins-bg` | insertions |
| `--redlines-del-fg`, `--redlines-del-bg` | deletions |
| `--redlines-move-fg` | moves |
| `--redlines-warn-fg` | notices |

### Checks

`tests/helpers/fragment_checks.py` uses `html.parser` and `re` only. Both fragments pass every check, on every fixture.

| # | Check |
|---|---|
| F1 | well-formed: one root, every start tag closed in order (void elements excepted), no stray end tags |
| F2 | contract items 2 and 3 |
| F3 | every `color`, `background`, `background-color`, `border*`, `outline`, `fill`, `stroke`, `box-shadow` and `font-family` declaration is `var(--redlines-NAME, FALLBACK)`, and the set of names used equals the twelve |
| F4 | contract item 6 |
| F5 | row structure: the row count equals `len(changes)`, and `data-index` runs 0 to n−1 in order; `data-kind` is in `CHANGE_KINDS`, and `data-address` starts with `/`; `data-source-address` is present exactly when the kind is not `insert`, and `data-test-address` exactly when it is not `delete`; `data-matched-by` is in `PASS_NAMES` ∪ {`unmatched`}, and `data-confidence` equals `repr(round(confidence, 4))` |
| F6 | filter parity: for a battery of `ChangeFilter`s, the attribute predicates select exactly the indices `filter_changes` selects. `kinds` reads `data-kind`; `address_prefixes` either address, segment-aligned; `labels` either label; `roles` `data-role`; `min_chars` `data-chars` (≥); `has_inline` `data-has-inline` |
| F7 | hostile input still passes F1 to F4, and each row's parsed text equals its node's text. The input contains `<script>alert(1)</script>`, `"`, `'` and `&`; `{++x++}` and `~>`; a backslash before a brace; bidi controls; and an unchanged run ending in a backslash before an edit |
| F8 | the header counts equal `statistics().counts`; each notice is present exactly when its condition holds; "1 change" is singular |
| F9 | determinism: two renders are byte-equal, and rendering `from_dict(to_dict(include_alignment=True))` gives the same bytes |

## Alternatives considered

**JavaScript renders from the v2 JSON in the iframe.** Interaction is unconstrained, and nothing extra travels in the tool result. Rejected: it is a second implementation and a second escaper, outside the core, against N7 and ADR-0016. It needs the alignment on the wire and both trees, and the M6 page would need the same renderer again, or would diverge.

**Headings as `<h1>` to `<h6>`.** The natural markup. Rejected: Starlight builds the M6 page's table of contents from its `h2` and `h3` elements, and an MCP host's page may do the same, so the fragment would rewrite its host's navigation.

**Inline `style=` attributes,** as the legacy `red_green` style writes them. Rejected: a content security policy that forbids inline styles would strip them.

**A stylesheet that declares the `--redlines-*` properties on `.redlines`.** Rejected: the fragment's own declaration would then override a shell's value set on an ancestor. Reading the properties with fallbacks lets the shell win by inheritance.

**Unscoped selectors.** Shorter CSS. Rejected: an injected `<style>` is document-global, and selectors for `ins`, `del` or `p` would restyle the rest of a Starlight page.

**A fullscreen handler inside the fragment.** Rejected: it needs a script, which breaks CSP safety, and it would bind the fragment to one host's protocol. The hook is a hidden button; the shell owns the protocol.

## Consequences

Positive: one implementation and one escaper. The MCP App, the site and a Python caller get the same bytes from the same comparison, so behaviour seen on the site is reproducible from Python, which is what N7 asks. A shell filters rows from their attributes alone, and F6 proves the parity with `filter_changes`. Theming is by inheritance. With no `id`s and every selector scoped, two fragments can share a page.

Negative: the app-only result grows, by about 30 KB on the sample pair, and linearly with the document: the change list costs about 2 KB plus about 1 KB per change node, and the document view about 1.1 times the test document plus about 40 bytes per block. Host limits on that size are unknown; M5 measures a 2,000-block pair, and the first remedy is dropping the document-view string, never storing anything. A host may block an injected `<style>`, which is why `STYLESHEET` is public and the shell may carry it. Which CSS variables hosts expose is unknown until M5's first run in Claude Desktop. Bidi controls still reorder text inside a block. Interaction beyond `<details>`, filtering and fullscreen is shell work, written once per shell. And the model-facing compact form still cannot say what an inserted container contains, since a container's `test_text` is empty; the fragments can, because they render from the trees. Whether the compact form gains a field, or the summary renderer covers it, is M5's decision.

## Revisit when

If an app-only result reaches a host's size limit, drop the document-view string before anything else. If a host blocks injected styles and the shell's own copy of `STYLESHEET` is not enough, that is a contract change and bumps the major. If a consumer must render without Python, such as a page that cannot load Pyodide, that is a second renderer and its own ADR, with this contract as its specification. If a shell needs a hook the contract lacks, add it as a minor version.

## Related

ADR-0011, ADR-0016, ADR-0019, ADR-0026, ADR-0033, ADR-0035, ADR-0037.
