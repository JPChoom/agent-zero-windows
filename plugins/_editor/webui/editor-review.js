// Review of agent changes in the Editor: CodeMirror's merge view shows each
// change against the text from before the agent edited the file, with Accept
// and Reject on every change (webui/vendor/codemirror).

import * as CM from "/vendor/codemirror/codemirror.bundle.js";

const LANGUAGES = {
  md: () => CM.markdown(),
  markdown: () => CM.markdown(),
  py: () => CM.python(),
  js: () => CM.javascript(),
  mjs: () => CM.javascript(),
  cjs: () => CM.javascript(),
  jsx: () => CM.javascript({ jsx: true }),
  ts: () => CM.javascript({ typescript: true }),
  tsx: () => CM.javascript({ typescript: true, jsx: true }),
  json: () => CM.json(),
  html: () => CM.html(),
  htm: () => CM.html(),
  css: () => CM.css(),
};

function theme(dark) {
  return CM.EditorView.theme(
    {
      "&": { height: "100%", fontSize: "13px", backgroundColor: "transparent", color: "var(--color-text)" },
      ".cm-scroller": { fontFamily: "var(--font-family-code, monospace)" },
      ".cm-gutters": { backgroundColor: "transparent", color: "var(--color-text-muted)", border: "none" },
      ".cm-content": { caretColor: "var(--color-text)" },
      ".cm-changedLine": { backgroundColor: dark ? "rgba(63, 194, 122, 0.12)" : "rgba(63, 194, 122, 0.14)" },
      ".cm-deletedChunk": { backgroundColor: dark ? "rgba(239, 95, 90, 0.12)" : "rgba(239, 95, 90, 0.1)" },
    },
    { dark },
  );
}

/** Show `after` (the agent's version) against `before`, with a button pair on
 * every change. Returns handles to read the result. */
export function mountReview(container, { before, after, extension = "", dark = true, onChange = null }) {
  const language = LANGUAGES[String(extension).toLowerCase()];
  const view = new CM.EditorView({
    parent: container,
    state: CM.EditorState.create({
      doc: after,
      extensions: [
        CM.lineNumbers(),
        CM.history(),
        CM.keymap.of([...CM.defaultKeymap, ...CM.historyKeymap]),
        CM.syntaxHighlighting(CM.defaultHighlightStyle, { fallback: true }),
        CM.EditorView.lineWrapping,
        theme(dark),
        language ? language() : [],
        CM.unifiedMergeView({ original: before, mergeControls: true, highlightChanges: true, gutter: true }),
        CM.EditorView.updateListener.of(() => onChange?.()),
      ],
    }),
  });
  return {
    view,
    remaining: () => CM.getChunks(view.state)?.chunks.length ?? 0,
    text: () => view.state.doc.toString(),
    destroy: () => view.destroy(),
  };
}
