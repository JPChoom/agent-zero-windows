import { createStore } from "/js/AlpineStore.js";
import { renderSafeMarkdown } from "/js/safe-markdown.js";

export const store = createStore("markdownModal", {
    title: "",
    content: "",
    error: null,
    viewer: "rendered",
    editor: null,

    open(title, content, options = {}) {
        this.title = title;
        this.content = content;
        this.error = null;
        this.viewer = options.viewer || "rendered";
        this.destroyEditor();
    },

    get renderedHtml() {
        if (!this.content) return "";
        return renderSafeMarkdown(this.content);
    },

    get isAce() {
        return this.viewer === "ace";
    },

    onOpen() {
        if (this.isAce) {
            this.scheduleEditorInit();
        }
    },

    scheduleEditorInit() {
        window.requestAnimationFrame(() => {
            if (!this.isAce || this.error) return;
            window.requestAnimationFrame(() => this.initEditor());
        });
    },

    initEditor() {
        const container = document.getElementById("markdown-ace-viewer-container");
        if (!container) return;

        this.destroyEditor();

        if (!window.ace?.edit) {
            this.error = "Editor library not loaded";
            return;
        }

        const editor = window.ace.edit("markdown-ace-viewer-container");
        if (!editor) {
            this.error = "Failed to initialize editor";
            return;
        }

        const darkMode = window.localStorage?.getItem("darkMode");
        const theme = darkMode !== "false" ? "ace/theme/github_dark" : "ace/theme/tomorrow";

        this.editor = editor;
        this.editor.setTheme(theme);
        this.editor.session.setMode("ace/mode/markdown");
        this.editor.setValue(this.content || "", -1);
        this.editor.setReadOnly(true);
        this.editor.clearSelection();
    },

    destroyEditor() {
        if (this.editor?.destroy) {
            this.editor.destroy();
        }
        this.editor = null;
    },

    cleanup() {
        this.destroyEditor();
        this.title = "";
        this.content = "";
        this.error = null;
        this.viewer = "rendered";
    },
});
