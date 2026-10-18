# ADR-0038: Render HTML once, in Python: one fragment contract

**Status:** Accepted
*Research on 18 October 2026, at the maintainer's request, confirmed the recommendation to render in Python, and amended three details that the text below includes: the app-only result carries the compact change list and the two fragments instead of the full v2 document; the stylesheet falls back to the hosts' standard CSS variables and declares no `color-scheme`; and the checks gain a tag and attribute allowlist over a hostile corpus.*
**Date:** 2026-10-18
**Deciders:** houfu

## Context

R20 asks for an HTML renderer, and ROADMAP § 5.7 keeps it minimal: a block list plus expandable redlines, where "the site adds interaction on top rather than a second renderer". [ADR-0035](0035-hosted-demo-server.md) gave the same renderer a second consumer. In the hosted demo it sent the app-only `compare` result, "the full v2 document with both block trees", to the MCP App's iframe, and ROADMAP's M3 row said the view "takes its data by `postMessage`, supports fullscreen, and themes from the host's CSS variables". M6 then shows the same views in a Starlight page, from the wheel running in Pyodide ([ADR-0019](0019-client-side-demo-site.md), [ADR-0026](0026-docs-site-on-astro-starlight.md)).

That leaves one fork: render the HTML in Python and hand the shells a string, or render it in the iframe, in JavaScript, from the v2 JSON. Measured on the section 3a sample pair:

- the change-list fragment is 12,900 bytes (2,560 gzipped): 1,862 bytes of CSS, about 0.2 KB of header and about 1.05 KB per row. Escaped as JSON inside a tool result it is 13,449 characters;
- the document view is about 16,000 bytes, about 16,700 characters escaped;
- the full v2 document is 156,081 bytes with `to_json()`'s default separators, and the compact form (`include_trees=False`) is 13,412.

The size matters, because Claude documents a maximum tool result of about 150,000 characters on claude.ai and Desktop ([Claude's connector guide](https://claude.com/docs/connectors/building/index), "Design within the size and timeout limits"). Above it, with code execution on, the app "receives a pointer to the stored file rather than the structured content it needs, so it never hydrates" ([MCP Apps troubleshooting](https://claude.com/docs/connectors/building/mcp-apps/troubleshooting)). The result ADR-0035 planned, the full v2 document plus both fragments, is about 186,000 characters on the sample pair. A renderer in the iframe would need the v2 document with `include_alignment=True`, because the document view places deletions from the alignment, and it would need both trees for subtree emission: about 154,000 to 173,000 characters, at or over the cap with no headroom. Splitting the result into two calls does not rescue it, because its document view alone needs both trees. It would also be a second implementation and a second escaper. N7 says that no comparison logic lives outside the core library, and [ADR-0016](0016-summary-renderer-in-core.md) records the standing principle "that no comparison or rendering logic lives outside the core". CI is not the obstacle: the Pyodide job already runs Node, so a JavaScript renderer could be tested. That plays no part in this decision.

This ADR first left two questions about hosts open: which CSS variables a host exposes, and whether a host's content security policy allows a `<style>` element that a script inserts. Research on 18 October 2026 answered both, from the MCP Apps specification, the source of the hosts that publish theirs, and the vendors' documentation, 93 sources in all:

- **CSP.** When a resource declares no policy, a host "MUST use" the specification's default, which includes `script-src 'self' 'unsafe-inline'` and `style-src 'self' 'unsafe-inline'` ([specification, 2026-01-26](https://github.com/modelcontextprotocol/ext-apps/blob/82221c0c8ce7661efa6771c9d461511b1650495f/specification/2026-01-26/apps.mdx?plain=1#L265-L290)). VS Code and Goose apply the same in their source ([VS Code](https://github.com/microsoft/vscode/blob/71f7505782a0272dd431371e204f4b2440c92521/src/vs/workbench/contrib/chat/browser/widget/chatContentParts/toolInvocationParts/chatMcpAppModel.ts#L244-L280), [Goose](https://github.com/aaif-goose/goose/blob/34adc70f13f2e5adbd5a1968ce976f25f6b911d8/crates/goose/src/acp/mcp_app_proxy.rs#L200-L222)), and Claude's own theming guide prescribes `applyHostFonts`, which inserts a `<style>` element from script ([transparent theming](https://claude.com/docs/connectors/building/mcp-apps/transparent-theming)). A `<style>` inserted with `innerHTML` takes effect wherever `'unsafe-inline'` is allowed ([HTML standard](https://html.spec.whatwg.org/multipage/semantics.html#the-style-element)). The same policies allow inline event handlers, so an `<img src=x onerror=…>` that reached the DOM would run ([MDN](https://developer.mozilla.org/en-US/docs/Web/API/Element/innerHTML#security_considerations)). CSP is therefore no backstop, and the escaper is the control. No host requires DOMPurify or any other sanitiser: not the specification, not Claude's documentation, not OpenAI's security page ([OpenAI](https://developers.openai.com/plugins/guides/security-privacy)), and not VS Code's source. OpenAI asks apps to treat a tool result "as untrusted input" ([ChatGPT UI guide](https://developers.openai.com/plugins/build/chatgpt-ui)); here the untrusted party is whoever wrote the documents.
- **Theming.** MCP Apps standardises the variable names: the `--color-background-*`, `--color-text-*` and `--color-border-*` families, `--font-sans`, `--font-mono`, `--border-radius-*` and others. It asks hosts to write their values with `light-dark()` and views to "set default fallback values" ([specification](https://github.com/modelcontextprotocol/ext-apps/blob/82221c0c8ce7661efa6771c9d461511b1650495f/specification/2026-01-26/apps.mdx?plain=1#L791-L957)). The view, not the host, writes them onto `:root`, and the SDK's `applyDocumentTheme` sets `color-scheme` there too ([SDK](https://github.com/modelcontextprotocol/ext-apps/blob/82221c0c8ce7661efa6771c9d461511b1650495f/src/styles.ts#L75-L224)). Claude publishes its values ([design guidelines](https://claude.com/docs/connectors/building/mcp-apps/design-guidelines)), and VS Code maps the names onto its own theme ([VS Code](https://github.com/microsoft/vscode/blob/006c4ca931cf8116352d6a3f1a2056320f5e6194/src/vs/workbench/contrib/mcp/browser/mcpToolCallUI.ts#L278-L390)). Starlight sets `color-scheme` on `<html>` as well, from the reader's theme picker ([Starlight](https://github.com/withastro/starlight/blob/292fb179cbf6e2cd970ced46359c520aa14a80b4/packages/starlight/src/style/reset.css#L12-L28)).
- **Precedent.** Single-file JavaScript bundles dominate. All 24 TypeScript example directories in the MCP Apps repository build one with `vite-plugin-singlefile` and render from `structuredContent` ([examples](https://github.com/modelcontextprotocol/ext-apps/tree/82221c0c8ce7661efa6771c9d461511b1650495f/examples)). Server-rendered fragments injected with `innerHTML` exist too: the htmx essay "Hypermedia Friendly MCP App Architecture" puts Django template partials in `structuredContent.html` ([htmx.org](https://htmx.org/essays/mcp-apps-hypermedia/)). No host or SDK forbids that, and none offers a special path for it.

## Decision

### Python renders, and the shells inject

- `Comparison.output_html()` and `Comparison.output_annotated(syntax="html")` are the only producers of change HTML in the project. `redlines-mcp` and `site/` inject them, and never render change data.
- The app-only `compare` result carries the compact change list, `to_dict(include_trees=False)`, plus both strings, rendered from the same `Comparison`. It does not carry the full v2 document, which the iframe no longer needs. On the sample pair it is about 44,000 characters, against about 186,000 with the full document. M5 names the keys. The model-facing compact form is unchanged.
- If a large document still takes the result past the cap, M5's size guard is the remedy. It measures the JSON-serialised result, since JSON escaping adds about 4.6% to the HTML, and past about 140,000 characters it either returns the change list alone and fetches the document view with a second app-only call, or sends `base64(gzip(html))`, about four times shorter, which the shell inflates with [`DecompressionStream`](https://developer.mozilla.org/en-US/docs/Web/API/DecompressionStream).
- The fragments are script-free markup, and every host policy that could be read allows the inline `<style>` they carry. CSP is not their safety net, since the same policies allow inline handlers: the escaper of contract item 4 and the allowlist of item 2, checked by F2 and F7, are. The ROADMAP's earlier wording, "takes its data by `postMessage`", holds at the shell: the strings arrive by `postMessage`, as the response to the app's own `tools/call` ([specification](https://github.com/modelcontextprotocol/ext-apps/blob/82221c0c8ce7661efa6771c9d461511b1650495f/specification/2026-01-26/apps.mdx?plain=1#L1391-L1490)).
- The contract below is versioned by `data-redlines-fragment="1.0"`. `redlines.renderers` exports `FRAGMENT_VERSION` and `STYLESHEET`.

| Milestone | Ships |
|---|---|
| M3 | the two fragment renderers; `STYLESHEET` and `FRAGMENT_VERSION`; checks F1 to F9 in `tests/helpers/fragment_checks.py`; the goldens |
| M5 | the static `ui://` shell, which injects both fragments; applies the host's standard CSS variables with the SDK's helpers (`applyHostStyleVariables`, `applyDocumentTheme`, `applyHostFonts`), which the stylesheet reads as fallbacks, so it needs no mapping code; un-hides the fullscreen button, wires it to `ui/request-display-mode` and then sets `data-redlines-display`; filters rows by their `data-*` attributes (F6), reading every value as text, writing it with `textContent`, never re-injecting it as HTML, and passing it through `CSS.escape` before it enters a selector; pushes `ui/update-model-context`; adds per-row actions and the intake drop zone; runs the size guard; and carries `STYLESHEET` in its own static `ui://` document if a host blocks an injected `<style>` |
| M6 | an Astro island that sets the standard names from Starlight's tokens on its container, for example `--color-text-primary: var(--sl-color-text)`; gets the same two strings from Pyodide; and injects them from its client-side script, since Astro's `set:html` runs only when a page is rendered ([Astro](https://docs.astro.build/en/reference/directives-reference/#sethtml)) |

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
   - exactly one `<style>`, the root's first child, which is where the HTML standard allows a `<style>` in body content ([HTML standard](https://html.spec.whatwg.org/multipage/semantics.html#the-style-element));
   - only the elements `section`, `style`, `header`, `p`, `span`, `button`, `ol`, `li`, `details`, `summary`, `div`, `code`, `ins`, `del`, `table`, `thead`, `tbody`, `tr`, `th` and `td`, and only the attributes `class`, `data-*`, `role`, `aria-level`, `hidden` and `type`;
   - none of the elements `<script>`, `<link>`, `<img>`, `<iframe>`, `<object>`, `<embed>`, `<base>`, `<meta>`, `<form>`, `<svg>`, `<math>`;
   - none of the attributes `src`, `href`, `srcset`, `action`, `formaction`;
   - no `@import` and no `url(` in the CSS.
3. **CSP-safe:** no `on*` attributes and no `style=` attributes. All styling comes through classes and `[data-*]` selectors. No MCP host whose policy could be read forbids inline styles; the rule holds for hygiene, and for a hash-based CSP if the site turns one on.
4. **Escaping:**
   - text goes through `html.escape(s, quote=False)`, and attribute values through `html.escape(s, quote=True)`, in double quotes;
   - every document-, profile- and engine-derived string passes through one of the two, labels, roles, addresses and `matched_by` included;
   - newlines are kept, and shown with `white-space: pre-wrap`.
5. **Theming:**
   - the stylesheet only reads `var(--redlines-NAME, FALLBACK)` and never declares a property, so a shell that sets `--redlines-*` on any ancestor wins by inheritance;
   - NAME is one of the thirteen in the table after this list;
   - FALLBACK is the host's standard variable, with a fallback of its own: for example `var(--color-text-primary, light-dark(LIGHT, DARK))` for a colour, `var(--font-sans, FONTS)` for a font and `var(--border-radius-sm, SIZE)` for a radius, using the standard name the table gives. A `var()` fallback may itself be a `var()` ([MDN](https://developer.mozilla.org/en-US/docs/Web/CSS/Reference/Values/var)). `--redlines-bg` falls back to `transparent`, because Claude asks apps not to paint a background ([transparent theming](https://claude.com/docs/connectors/building/mcp-apps/transparent-theming));
   - the fragment declares no `color-scheme`. It inherits the scheme its shell sets on `<html>`, so `light-dark()` follows the theme the reader chose. Where `light-dark()` is unsupported (it needs Chrome 123, Firefox 120 or Safari 17.5), the declaration falls back to inherited colours.
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

The thirteen theme properties of item 5, the standard names they fall back to, and Claude's published values for reference:

| Property | Used for | Falls back to | Claude, light / dark |
|---|---|---|---|
| `--redlines-font` | body font | `--font-sans` | Anthropic Sans |
| `--redlines-mono` | addresses and scores | `--font-mono` | ui-monospace, monospace |
| `--redlines-fg` | text | `--color-text-primary` | #141413 / #FAF9F5 |
| `--redlines-bg` | background | `transparent`, with no standard name | — |
| `--redlines-muted` | breadcrumb, role, metadata | `--color-text-secondary` | #3D3D3A / #C2C0B6 |
| `--redlines-border` | row rules | `--color-border-tertiary` | #1F1E1D / #DEDCD1, at 15% |
| `--redlines-ins-fg`, `--redlines-ins-bg` | insertions | `--color-text-success`, `--color-background-success` | #265B19 / #7AB948; #E9F1DC / #1B4614 |
| `--redlines-del-fg`, `--redlines-del-bg` | deletions | `--color-text-danger`, `--color-background-danger` | #7F2C28 / #EE8884; #F7ECEC / #602A28 |
| `--redlines-move-fg` | moves | `--color-text-info` | #3266AD / #80AADD |
| `--redlines-warn-fg` | notices | `--color-text-warning` | #5A4815 / #D1A041 |
| `--redlines-radius` | corners | `--border-radius-sm` | — |

### Checks

`tests/helpers/fragment_checks.py` uses `html.parser` and `re` only. Both fragments pass every check, on every fixture.

| # | Check |
|---|---|
| F1 | well-formed: one root, every start tag closed in order (void elements excepted), no stray end tags |
| F2 | contract items 2 and 3, the allowlist of elements and attributes included |
| F3 | every `color`, `background`, `background-color`, `border*`, `outline`, `fill`, `stroke`, `box-shadow` and `font-family` declaration is `var(--redlines-NAME, FALLBACK)`; the set of names used equals the thirteen; each FALLBACK is a `var()` of the standard name the table gives, or `transparent` for `--redlines-bg`; and no rule declares `color-scheme` |
| F4 | contract item 6 |
| F5 | row structure: the row count equals `len(changes)`, and `data-index` runs 0 to n−1 in order; `data-kind` is in `CHANGE_KINDS`, and `data-address` starts with `/`; `data-source-address` is present exactly when the kind is not `insert`, and `data-test-address` exactly when it is not `delete`; `data-matched-by` is in `PASS_NAMES` ∪ {`unmatched`}, and `data-confidence` equals `repr(round(confidence, 4))` |
| F6 | filter parity: for a battery of `ChangeFilter`s, the attribute predicates select exactly the indices `filter_changes` selects. `kinds` reads `data-kind`; `address_prefixes` either address, segment-aligned; `labels` either label; `roles` `data-role`; `min_chars` `data-chars` (≥); `has_inline` `data-has-inline` |
| F7 | hostile input still passes F1 to F4, so the allowlist of item 2 holds under it, and each row's parsed text equals its node's text. The input contains `<script>alert(1)</script>`, `<img src=x onerror=alert(1)>`, `"><script>alert(1)</script>` and `</style>`; `"`, `'` and `&`; `{++x++}` and `~>`; a backslash before a brace; bidi controls; and an unchanged run ending in a backslash before an edit |
| F8 | the header counts equal `statistics().counts`; each notice is present exactly when its condition holds; "1 change" is singular |
| F9 | determinism: two renders are byte-equal, and rendering `from_dict(to_dict(include_alignment=True))` gives the same bytes |

## Alternatives considered

**JavaScript renders from the v2 JSON in the iframe.** Interaction is unconstrained. Rejected: it is a second implementation and a second escaper, outside the core, against N7 and ADR-0016. It needs both trees and the alignment, about 154,000 to 173,000 characters on the sample pair, at or over Claude's cap with no headroom, and a two-call split does not help, because its document view alone needs both trees. The M6 page would need the same renderer again, or would diverge.

**The full v2 document in the app-only result, as ADR-0035 first had it.** Rejected: with both fragments it is about 186,000 characters on the sample pair, over Claude's cap, and once Python renders the views the iframe reads nothing in it that the compact change list lacks.

**Headings as `<h1>` to `<h6>`.** The natural markup. Rejected: Starlight builds the M6 page's table of contents from its `h2` and `h3` elements, and an MCP host's page may do the same, so the fragment would rewrite its host's navigation.

**Inline `style=` attributes,** as the legacy `red_green` style writes them. Rejected: no MCP host whose policy could be read forbids them, but a hash-based CSP on the site would, and contract item 3 keeps every style in the one stylesheet.

**A stylesheet that declares the `--redlines-*` properties on `.redlines`.** Rejected: the fragment's own declaration would then override a shell's value set on an ancestor. Reading the properties with fallbacks lets the shell win by inheritance.

**`color-scheme: light dark` on the fragment root,** as this ADR first had it. Rejected: a declaration on the root beats the scheme the shell sets on `<html>`, and `light-dark()` then resolves from the reader's operating system, or inside an iframe from the embedding element's scheme ([MDN](https://developer.mozilla.org/en-US/docs/Web/CSS/Reference/At-rules/@media/prefers-color-scheme)), not from the theme the reader chose. On the docs site, a reader whose system is in light mode and who picks Starlight's dark theme would get light fragment colours.

**Unscoped selectors.** Shorter CSS. Rejected: an injected `<style>` is document-global, and selectors for `ins`, `del` or `p` would restyle the rest of a Starlight page.

**A fullscreen handler inside the fragment.** Rejected: a `<script>` inserted with `innerHTML` does not run, an inline handler would put behaviour into markup the allowlist forbids, and either would bind the fragment to one host's protocol. The hook is a hidden button; the shell owns the protocol.

**A sanitiser in the shell.** Rejected as a requirement: no host asks for one, and DOMPurify would have to be bundled into the shell for no guarantee the allowlist does not already give. The browser's `setHTML` with its default configuration removes `<style>`, `<details>`, `<summary>`, `<button>` and every `data-*` attribute ([MDN](https://developer.mozilla.org/en-US/docs/Web/API/HTML_Sanitizer_API/Default_sanitizer_configuration)), which would gut the fragment. A shell may still use `setHTML(html, { sanitizer: {} })` where the browser has it, as defence in depth.

**Other shapes the research ruled out.** Running the core in Pyodide inside the app iframe: host policies lack `wasm-unsafe-eval`, so WebAssembly cannot compile there ([ext-apps #605](https://github.com/modelcontextprotocol/ext-apps/issues/605)). Serving the rendered page as the `ui://` resource itself: hosts "MAY prefetch and cache" that resource ([specification](https://github.com/modelcontextprotocol/ext-apps/blob/82221c0c8ce7661efa6771c9d461511b1650495f/specification/2026-01-26/apps.mdx?plain=1#L386-L409)), the maintainers declined templated resources ([ext-apps #298](https://github.com/modelcontextprotocol/ext-apps/issues/298)), and a stateless server cannot tie a later `resources/read` to a `compare` call. A nested `<iframe srcdoc>`: unnecessary for script-free markup, and the shell's host variables and the SDK's auto-resize would not reach the nested document. A display model painted by a generic JavaScript renderer, as FastMCP's Prefab does: it costs what a JavaScript renderer costs and sends no less.

## Consequences

Positive: one implementation and one escaper. The MCP App, the site and a Python caller get the same bytes from the same comparison, so behaviour seen on the site is reproducible from Python, which is what N7 asks. The app-only result is about 44,000 characters on the sample pair, under a third of Claude's cap. The M5 shell needs no theme-mapping code, and a host that sends no variables still gets the fragment's own `light-dark()` colours. A shell filters rows from their attributes alone, and F6 proves the parity with `filter_changes`. With no `id`s and every selector scoped, two fragments can share a page.

Negative: the result still grows linearly with the document. The change list costs about 2 KB plus about 1 KB per change node, and the document view about 1.1 times the test document plus about 40 bytes per block. So the result reaches Claude's cap at roughly a 100 to 120 KB test document, and a 2,000-block document exceeds it. That is what M5's size guard is for, and its compression is the project's own technique, which neither the specification nor Claude's or OpenAI's documentation mentions. The escaper and the allowlist are the only injection control, because hosts allow inline handlers. On the site the fragment has a weaker sandbox still: project sites share the `houfu.github.io` origin ([GitHub Pages](https://docs.github.com/en/pages/getting-started-with-github-pages/what-is-github-pages)), and nothing sandboxes the island. Anything the shell forwards with `ui/update-model-context` is text a counterparty may have written, on its way to the model. If the site turns on Astro's hash-based CSP, the injected `<style>` needs `sha256(STYLESHEET)` among its style hashes ([Astro](https://docs.astro.build/en/reference/configuration-reference/#securitycsp)), which works because `STYLESHEET` is a constant. Bidi controls still reorder text inside a block. Interaction beyond `<details>`, filtering and fullscreen is shell work, written once per shell. And the model-facing compact form still cannot say what an inserted container contains, since a container's `test_text` is empty; the fragments can, because they render from the trees. Whether the compact form gains a field, or the summary renderer covers it, is M5's decision.

## Revisit when

Three facts are still to test in M5, before the shell is frozen. First, whether Claude applies its cap to the results of app-initiated `tools/call` requests, which its documentation does not carve out; if it does not, the size guard can relax. Second, Claude's actual iframe CSP header, readable in Desktop's developer tools; if it blocks the injected `<style>`, the shell carries `STYLESHEET`, and dropping the `<style>` from the fragment would be a contract change that bumps the major. Third, whether Codex and ChatGPT send `hostContext.styles.variables`, which neither documents; if they do not, the fragment's own fallbacks show there. Codex has shown MCP app panels since Codex app 26.423, on 24 April 2026 ([changelog](https://learn.chatgpt.com/docs/changelog)). If host policies gain `wasm-unsafe-eval`, running the core inside the app iframe stops being ruled out, and this decision is worth reopening. If a consumer must render without Python, such as a page that cannot load Pyodide, that is a second renderer and its own ADR, with this contract as its specification. If a shell needs a hook the contract lacks, add it as a minor version.

## Related

ADR-0011, ADR-0016, ADR-0019, ADR-0026, ADR-0033, ADR-0035, ADR-0037.
