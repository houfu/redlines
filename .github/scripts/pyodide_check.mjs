#!/usr/bin/env node
// Imports the built redlines wheel inside a Pyodide (WASM CPython) runtime
// and exercises the public entry points that M1 promises will load in the
// browser (ADR-0019, PRD N5). Run from the repository root:
//
//   node .github/scripts/pyodide_check.mjs dist/redlines-<version>-py3-none-any.whl
//
// PYODIDE_INDEX_URL, when set, points loadPyodide at a local extracted
// Pyodide distribution instead of the default CDN, so the check can run
// offline (e.g. in a sandboxed dev environment). It is unset in the normal
// CI job, which lets Pyodide resolve its own CDN packages.
import { readFileSync } from "node:fs";
import { basename } from "node:path";
import { loadPyodide } from "pyodide";

async function main() {
  const wheelPath = process.argv[2];
  if (!wheelPath) {
    console.error("usage: node pyodide_check.mjs <path-to-wheel>");
    process.exit(1);
  }

  const indexURL = process.env.PYODIDE_INDEX_URL;
  const py = await loadPyodide(indexURL ? { indexURL } : {});
  console.log(`Loaded Pyodide ${py.version}${indexURL ? ` (indexURL=${indexURL})` : ""}`);

  await py.loadPackage("micropip");
  const micropip = py.pyimport("micropip");

  // Stage the freshly built wheel into Pyodide's in-memory filesystem so
  // micropip can install it with an emfs: URL, exactly as the CI job will
  // install the wheel it just built with `uv build --wheel`.
  const wheelBytes = readFileSync(wheelPath);
  const emfsPath = `/tmp/${basename(wheelPath)}`;
  py.FS.writeFile(emfsPath, new Uint8Array(wheelBytes));

  try {
    await micropip.install(`emfs:${emfsPath}`);
  } catch (err) {
    console.error(`micropip.install failed for ${wheelPath}:`);
    console.error(err);
    process.exit(1);
  }

  // Import every module M1 adds under redlines.* plus the profile loader,
  // and confirm a minimal profile actually loads. Then import the M3
  // renderer package -- nothing star-imports it from redlines/__init__
  // until the Comparison render methods arrive -- and run its core once:
  // build the view of a two-paragraph pair and render it in place with the
  // legacy "none" set (ADR-0037). Each renderer adds its own method's call
  // below. Left uncaught so a failure propagates as a PythonError carrying
  // the formatted CPython traceback, which we print before exiting non-zero.
  const checkScript = `
import redlines
import redlines.blocks
import redlines.readers
import redlines.readers.detect
import redlines.profiles
import redlines.renderers
import redlines.renderers._escape
import redlines.renderers._inplace
import redlines.renderers._marks
import redlines.renderers._view
from redlines import compare
from redlines.profiles import load_profile
from redlines.renderers._inplace import render_inplace
from redlines.renderers._marks import LEGACY
from redlines.renderers._view import build_view

profile = load_profile("name: x")
assert profile.name == "x", f"unexpected profile name: {profile.name!r}"

pair = compare(
    "The quick brown fox jumps over the lazy dog.\\n\\nA second paragraph stays.",
    "The quick brown fox walks past the lazy dog.\\n\\nA second paragraph stays.",
    format="text",
)
view = build_view(pair)
assert len(view.children) == 2, f"unexpected view: {view.children!r}"
rendered = render_inplace(pair, LEGACY["none"], syntax="text", roles=False)
expected = (
    "The quick brown fox <del>jumps over </del><ins>walks past </ins>the lazy dog."
    "\\n\\nA second paragraph stays."
)
assert rendered == expected, f"unexpected in-place render: {rendered!r}"

# Comparison.output_markdown (#179) and Comparison.output_rich (#180); rich
# loads under Pyodide, and _rich.py is the only renderer module importing it.
# No backslash escapes here: this is a JavaScript template literal.
markdown = pair.output_markdown("none")
assert markdown == expected, f"unexpected output_markdown: {markdown!r}"
rich_text = pair.output_rich()
rich_plain = (chr(10) * 2).join(
    [
        "1 change: 0 inserted, 0 deleted, 1 modified, 0 moved, 0 renumbered",
        "The quick brown fox jumps over walks past the lazy dog.",
        "A second paragraph stays.",
    ]
)
assert rich_text.plain == rich_plain, f"unexpected output_rich: {rich_text.plain!r}"
styles = [str(span.style) for span in rich_text.spans]
assert styles == ["bold", "strike red", "green"], f"unexpected output_rich styles: {styles!r}"
f"redlines ok; profile {profile.name!r} loaded; renderer core ok"
`;

  let result;
  try {
    result = await py.runPythonAsync(checkScript);
  } catch (err) {
    console.error("Pyodide import check FAILED:");
    console.error(err);
    process.exit(1);
  }

  console.log(result);
  console.log("Pyodide import check passed.");
}

main().catch((err) => {
  console.error("Pyodide import check FAILED:");
  console.error(err);
  process.exit(1);
});
