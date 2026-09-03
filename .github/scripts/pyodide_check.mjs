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
  // and confirm a minimal profile actually loads. Left uncaught so a
  // failure propagates as a PythonError carrying the formatted CPython
  // traceback, which we print before exiting non-zero.
  const checkScript = `
import redlines
import redlines.blocks
import redlines.readers
import redlines.readers.detect
import redlines.profiles
from redlines.profiles import load_profile

profile = load_profile("name: x")
assert profile.name == "x", f"unexpected profile name: {profile.name!r}"
f"redlines ok; profile {profile.name!r} loaded"
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
