/**
 * useCodemirror — manages a CodeMirror 6 editor instance.
 *
 * Creates/destroys the EditorView when the container ref changes.
 * Syncs external content and read-only state without re-creating the view.
 */

import { useRef, useEffect, useCallback } from "react";
import { EditorState } from "@codemirror/state";
import { EditorView, keymap, lineNumbers, drawSelection, highlightActiveLine } from "@codemirror/view";
import { markdown } from "@codemirror/lang-markdown";
import { defaultKeymap, history, historyKeymap } from "@codemirror/commands";
import { syntaxHighlighting, defaultHighlightStyle, bracketMatching } from "@codemirror/language";

// Minimal warm-toned theme
const vanillaTheme = EditorView.theme({
  "&": {
    fontSize: "14px",
    fontFamily: "ui-monospace, 'SF Mono', 'Cascadia Code', Consolas, monospace",
    height: "100%",
  },
  ".cm-content": {
    padding: "12px 16px",
    caretColor: "#78716c",
  },
  ".cm-gutters": {
    backgroundColor: "transparent",
    borderRight: "none",
    color: "#d6d3d1",
  },
  ".cm-activeLine": {
    backgroundColor: "#fafaf910",
  },
  ".cm-selectionBackground": {
    backgroundColor: "#78716c30 !important",
  },
  "&.cm-focused .cm-selectionBackground": {
    backgroundColor: "#78716c40 !important",
  },
  ".cm-cursor": {
    borderLeftColor: "#78716c",
  },
  ".cm-scroller": {
    overflow: "auto",
  },
});

interface UseCodemirrorOptions {
  content: string;
  readOnly: boolean;
  onChange: (value: string) => void;
  /** Current file path — triggers view re-creation on every file switch. */
  filePath: string | null;
}

export function useCodemirror({ content, readOnly, onChange, filePath }: UseCodemirrorOptions) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const viewRef = useRef<EditorView | null>(null);
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;

  // Always-current content ref — lets setContainer read the latest value
  // without depending on it (which would re-create the editor on every keystroke)
  const contentRef = useRef(content);
  contentRef.current = content;

  // Track what content we last dispatched to avoid echoing updates
  const lastExternalContent = useRef(content);

  const setContainer = useCallback(
    (el: HTMLDivElement | null) => {
      // Teardown old view
      if (viewRef.current) {
        viewRef.current.destroy();
        viewRef.current = null;
      }

      containerRef.current = el;
      if (!el) return;

      // Read the latest content from the ref (avoids stale closure when
      // readOnly stays the same across file switches)
      const initialContent = contentRef.current;
      // Sync the guard so the useEffect below doesn't fire a redundant dispatch
      lastExternalContent.current = initialContent;

      const updateListener = EditorView.updateListener.of((update) => {
        if (update.docChanged) {
          const value = update.state.doc.toString();
          lastExternalContent.current = value;
          onChangeRef.current(value);
        }
      });

      const state = EditorState.create({
        doc: initialContent,
        extensions: [
          lineNumbers(),
          history(),
          drawSelection(),
          highlightActiveLine(),
          bracketMatching(),
          syntaxHighlighting(defaultHighlightStyle),
          markdown(),
          keymap.of([...defaultKeymap, ...historyKeymap]),
          vanillaTheme,
          EditorState.readOnly.of(readOnly),
          updateListener,
        ],
      });

      viewRef.current = new EditorView({ state, parent: el });
    },
    // Re-create view when readOnly OR filePath changes.
    // readOnly: extensions are baked in at creation time (EditorState.readOnly).
    // filePath: every file switch gets a fresh view — avoids stale state when
    //           switching between two files with the same readOnly value (e.g.
    //           two wiki-vault files both read-only: without filePath here the
    //           view would keep showing the previous file's content).
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [readOnly, filePath],
  );

  // Sync external content into existing view (e.g. file switch)
  useEffect(() => {
    const view = viewRef.current;
    if (!view) return;
    if (content === lastExternalContent.current) return;

    lastExternalContent.current = content;
    view.dispatch({
      changes: { from: 0, to: view.state.doc.length, insert: content },
    });
  }, [content]);

  // Insert voice-transcribed text at the current cursor position
  useEffect(() => {
    function handleVoiceTranscript(e: Event) {
      const view = viewRef.current;
      if (!view) return;
      const transcript = (e as CustomEvent<{ transcript: string }>).detail
        ?.transcript;
      if (!transcript) return;

      const cursor = view.state.selection.main.head;
      view.dispatch({
        changes: { from: cursor, insert: transcript },
        selection: { anchor: cursor + transcript.length },
      });
      view.focus();
    }

    window.addEventListener("vanilla:voice-transcript", handleVoiceTranscript);
    return () =>
      window.removeEventListener(
        "vanilla:voice-transcript",
        handleVoiceTranscript,
      );
  }, []); // viewRef is a stable ref — no deps needed

  return { setContainer };
}
