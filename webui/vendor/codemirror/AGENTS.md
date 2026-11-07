# CodeMirror Vendor DOX

## Purpose

- Own the vendored CodeMirror 6 bundle used for the Editor's review of agent changes (merge view with per-change Accept and Reject).

## Ownership

- `codemirror.bundle.js` is one minified ES module built from `build-entry.js` with esbuild. It exports only what `build-entry.js` lists.
- `LICENSE` is CodeMirror's MIT license; every package in the bundle (@codemirror/*, @lezer/*, style-mod, w3c-keyname, crelt, @marijn/find-cluster-break) is MIT, and their notices are kept at the end of the bundle (`--legal-comments=eof`).

## Local Contracts

- Do not hand-edit the bundle. To change what it exports, edit `build-entry.js` and rebuild.
- Built 2026-11-07 from @codemirror/merge 6.12.3, @codemirror/view 6.43.15, @codemirror/state 6.7.6, @codemirror/commands 6.11.1, @codemirror/language 6.13.1 and the lang-markdown, lang-python, lang-javascript, lang-json, lang-html and lang-css packages.

## Work Guidance

- Rebuild in an empty folder outside the repository: `npm install @codemirror/state @codemirror/view @codemirror/commands @codemirror/language @codemirror/merge @codemirror/lang-markdown @codemirror/lang-python @codemirror/lang-javascript @codemirror/lang-json @codemirror/lang-html @codemirror/lang-css esbuild`, then `npx esbuild build-entry.js --bundle --format=esm --minify --legal-comments=eof --outfile=codemirror.bundle.js`. Never commit `node_modules`.

## Verification

- Smoke-test the Editor's review of an agent change after updating.

## Child DOX Index

No child DOX files.
