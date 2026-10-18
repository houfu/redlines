# ADR-0035: A hosted demo server over streamable HTTP that retains nothing

**Status:** Accepted
**Date:** 2026-10-18
**Deciders:** houfu

## Context

The 1.0 plan put the MCP server on stdio only ([ADR-0018](0018-mcp-tools-prompts-resources.md), ROADMAP
§5.4), because Claude Code, Claude Desktop and Cursor all launched local servers, and left streamable HTTP to
1.1 for hosted agents. Two things changed between September and October 2026.

First, the user journey we want to show is in Claude Desktop: a lawyer compares two drafts, sees the changes
rendered as an MCP App inside the conversation, browses them, and tells Claude what to do about them. A
hosted instance that anyone can add to Claude is the cheapest way to show that, and in Claude it is a
*custom connector*: a streamable HTTP server at a public URL, reached through Anthropic's infrastructure. The
connector dialog allows "No sign-in", and a Free plan may add one custom connector, so a demo needs no OAuth.
[ADR-0020](0020-mcp-before-site.md) anticipated this in its revisit clause: "if an opportunity makes a public
demo urgent, the order can be flipped".

Second, a file attached in Claude Desktop goes to Claude, not to any MCP server. There is no host path from an
attachment to a tool. The only way to get a lawyer's documents to the server without the model copying them
is for the MCP App's own iframe to be the drop zone and to call a tool the model cannot see. That makes the
server's handling of document bytes a design question, and the maintainer's answer is firm: a server on the
public internet should not store anything it receives.

"Zero data retention" is a term from the model-vendor relationship; it is not quite the right frame here.
redlines is not calling a model, Claude is calling redlines. The promise this ADR makes is the server's own:
nothing it receives outlives the HTTP response that answers it.

## Decision

### 1. Streamable HTTP moves into 1.0

`redlines-mcp` 0.1 ships both transports. stdio stays the default for local installs; `redlines-mcp --http
--port N` serves the single MCP endpoint. In the 2026-07-28 protocol the core is stateless and both transports
carry the same per-request metadata, so this is a transport switch in the SDK, not a second server. The
server validates the `Origin` header on every request and answers 403 when it is present and not allowed,
rejects requests whose `Mcp-Method` and `Mcp-Name` headers disagree with the body, and binds to localhost
unless told otherwise. Those three are the spec's own requirements for this transport.

### 2. The public instance is process-and-forget

The demo server holds a request's documents in memory while it computes the response and then drops them.
Concretely:

- **No handles, no TTL, no store.** There is no `store_documents`, no `comparison_id`, no "fetch it later"
  tool. Every tool call carries everything it needs and the server forgets it on return. The journey sketch's
  handle-based shape is withdrawn.
- **The iframe is the state.** The MCP App keeps the two documents and the full comparison in browser memory
  for as long as the view is open, and re-sends the documents when it needs the server again. For text-sized
  inputs this costs nothing worth measuring.
- **Two answers from one comparison.** The app calls an app-only `compare` (visibility `["app"]`); its result,
  the full v2 document with both block trees, goes to the iframe and nowhere else. The app then pushes the
  compact change list to the model with `ui/update-model-context`. The model-facing `compare` takes inline
  text and returns the compact form. Both are stateless. *Amended 18 October 2026
  ([ADR-0038](0038-render-html-once-in-python.md)): the app-only result carries the compact change list and
  the two HTML views rendered from the same `Comparison`, and not the full v2 document, which the iframe no
  longer needs. It still goes to the iframe and nowhere else, and it is the comparison the iframe keeps. On
  the sample pair it is about 63,000 characters; with the full document it was about 186,000, over the
  150,000-character tool result Claude documents.*
- **The compact form is self-sufficient.** Every change node already carries both addresses, both labels and
  both texts ([ADR-0033](0033-change-tree-wire-format.md)), so Claude needs no follow-up tool to discuss a
  change. There is no `get_change`.
- **Verify is app-triggered in this flow.** Claude never had the originals, so the lawyer drops the edited
  document into the app and the app sends original plus edited together. The model-facing
  `verify(original, edited, allowed)` remains for the paste flow.
- **No bodies in logs.** The server logs method, tool name, byte counts, timings and outcome. It never logs
  arguments, results or document text, and runs with no writable volume.

### 3. What a no-auth public endpoint must refuse

- **No filesystem reads.** [ADR-0033](0033-change-tree-wire-format.md) already rules that a bare string is
  content, never a path. The shared argument layer of [ADR-0025](0025-cli-as-thin-skin.md) resolves paths for
  the CLI; in HTTP mode that resolution is disabled, not merely unused.
- **Built-in profiles only on the public instance.** Profiles are regexes ([ADR-0028](0028-profile-file-format.md))
  and a user-supplied profile runs on the server. Catastrophic backtracking is the realistic abuse of a free
  endpoint, so the hosted demo accepts `profile` as a built-in name and nothing else. `validate_profile`
  and the profile-authoring prompts stay available on local installs. A regex execution timeout is the
  alternative if demand for custom profiles on the demo appears.
- **Compute caps.** R34 size limits, [ADR-0032](0032-alignment-passes.md)'s run-wide `max_comparisons`, the
  SDK's per-request timeout, and per-IP rate limiting at the edge. Errors name the limit.
- **TLS and a stated retention policy.** The intake view and the connector's description both say what the
  server keeps (nothing after the response), what it logs (counts), and that traffic transits Anthropic's
  infrastructure because that is how custom connectors work. The demo is not for confidential documents and
  says so.

### 4. Enterprise deployment is out of scope

The repository ships a container image and a page that says how to run the HTTP server behind an
organisation's own URL and auth. How an enterprise gets it into Claude (an Owner adding an org-wide
connector, an MCPB wrapper, a plugin) is their decision. The project does not build a Node or Pyodide bundle
for Claude Desktop.

### 5. DOCX stays in 1.1

The demo is text and markdown. The intake view says "paste, or save as .txt or .md". The DOCX reader keeps
its place as the first item of 1.1.

## Alternatives considered

**Handles with a short TTL, in memory.** The natural MCP Apps shape, and what the first journey sketch
assumed. Rejected: it is storage, however brief, on a server that takes documents from strangers, and the
iframe can hold the same state at no cost to the user.

**Encrypted-at-rest storage with per-user keys.** Solves the wrong problem; the maintainer does not want
custody at all.

**OAuth on the demo.** Would allow per-user quotas. Rejected for 0.1: it adds a sign-in step to a demo whose
point is "add the URL and drop two files", and the no-sign-in dialog exists. Revisit if abuse appears.

**A Node MCPB bundle running the wheel in Pyodide.** Would give lawyers a one-click local install with no
Python. Not pursued: it is enterprise packaging, which this ADR leaves to enterprises.

**Keep HTTP in 1.1 and demo over stdio.** Rejected: a stdio demo needs a terminal and Python on the viewer's
machine, which is exactly the audience the demo is for not having.

## Consequences

Positive: a demo anyone can add to Claude in one dialog; a server with no custody of documents and nothing
to breach; one codebase for stdio and HTTP; the M3 HTML renderer gets a second consumer (the app view) at
the moment it is written.

Negative: documents cross the network on every call rather than once; the app cannot resume a view after the
iframe is torn down (the host's stored tool result is what persists, under the user's own Claude retention);
custom profiles are not demonstrable on the public instance; the public instance is a running cost and an
abuse surface that needs rate limits and monitoring from day one.

Edits this ADR implies, to land after the M2 stack (#147 to #158) merges because #147 touches the same files:

- ROADMAP §5.4: "**Reversed, 18 October 2026.** Streamable HTTP joins M5; a hosted demo in Claude Desktop is a
  custom connector and needs it (ADR-0035)." M5 gains rows for the HTTP transport, the intake tool and its
  `ui://` resource, the app-only tool variants, and the container image.
- PRD R31: streamable HTTP becomes **Must** for 1.0. R34 gains "and the public instance accepts built-in
  profiles only".
- ADR-0018, transport paragraph: both transports in 0.1; the stateless-and-forgetting rule for anything
  reachable from the internet.
- ADR-0020: revisit clause exercised; the order is unchanged (MCP still precedes the site) but the MCP
  deliverable now includes the hosted instance.
- ADR-0033: unchanged in substance. The compact model-facing output is a projection of the v2 document, which
  is why the schema's `required` list no longer demands the block trees (ADR-0033, amendment of 2026-10-18, #164).

## Revisit when

If abuse of the no-auth endpoint outruns rate limiting, add OAuth with per-user quotas. If users of the demo
repeatedly ask for their own profiles, add a regex timeout and lift the built-in-only rule. If Claude Desktop
gains a host path from attachments to tools, the intake view can become optional. If re-sending documents on
every call becomes a measured cost, the first thing to try is compression, not storage.

## Related

ADR-0017, ADR-0018, ADR-0020, ADR-0025, ADR-0028, ADR-0032, ADR-0033. The payload measurement is recorded in
ADR-0033's amendment; the MCP Apps, Codex and Claude connector facts are from the specification and the two vendors'
documentation as read on 18 October 2026.
