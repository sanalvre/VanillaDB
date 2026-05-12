/**
 * EditorPanel — CodeMirror 6 markdown editor with React.memo isolation.
 */

import { memo, useCallback } from "react";
import { useEditorStore } from "@/stores/editorStore";
import { useCodemirror } from "./useCodemirror";

export const EditorPanel = memo(function EditorPanel() {
  const activeFilePath = useEditorStore((s) => s.activeFilePath);
  const fileContent = useEditorStore((s) => s.fileContent);
  const isReadOnly = useEditorStore((s) => s.isReadOnly);
  const isDirty = useEditorStore((s) => s.isDirty);
  const isLoading = useEditorStore((s) => s.isLoading);
  const openError = useEditorStore((s) => s.openError);
  const updateContent = useEditorStore((s) => s.updateContent);
  const saveFile = useEditorStore((s) => s.saveFile);

  const handleChange = useCallback(
    (value: string) => updateContent(value),
    [updateContent],
  );

  const { setContainer } = useCodemirror({
    content: fileContent ?? "",
    readOnly: isReadOnly,
    onChange: handleChange,
    filePath: activeFilePath,
  });

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "s") {
        e.preventDefault();
        saveFile();
      }
    },
    [saveFile],
  );

  if (openError) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-2 bg-white px-6 text-center dark:bg-zinc-900">
        <svg width="28" height="28" viewBox="0 0 24 24" fill="none" className="text-red-400 dark:text-red-500">
          <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="1.5" />
          <path d="M12 7v5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
          <circle cx="12" cy="16" r="0.75" fill="currentColor" />
        </svg>
        <p className="text-sm font-medium text-stone-600 dark:text-zinc-300">{openError}</p>
        <p className="text-xs text-stone-400 dark:text-zinc-500">
          Your vault may have moved. Check Settings → Vault to reconfigure.
        </p>
      </div>
    );
  }

  if (!activeFilePath) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-2 bg-white text-stone-400 dark:bg-zinc-900 dark:text-zinc-600">
        <svg width="32" height="32" viewBox="0 0 32 32" fill="none" className="opacity-30">
          <rect x="6" y="4" width="20" height="24" rx="2" stroke="currentColor" strokeWidth="1.5" fill="none" />
          <line x1="10" y1="11" x2="22" y2="11" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
          <line x1="10" y1="15" x2="22" y2="15" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
          <line x1="10" y1="19" x2="18" y2="19" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
        </svg>
        <p className="text-sm">Select a file to edit</p>
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="flex flex-1 items-center justify-center bg-white text-sm text-stone-400 dark:bg-zinc-900">
        <div className="h-4 w-4 animate-spin rounded-full border border-stone-300 border-t-stone-500 dark:border-zinc-700 dark:border-t-zinc-300" />
      </div>
    );
  }

  const parts = activeFilePath.split("/");
  const fileName = parts.pop() || activeFilePath;
  const parentPath = parts.join("/");

  return (
    <div className="flex flex-1 flex-col overflow-hidden bg-white dark:bg-zinc-900" onKeyDown={handleKeyDown}>
      {/* Breadcrumb bar */}
      <div className="flex items-center gap-1.5 border-b border-stone-100 px-3 py-1.5 text-xs min-w-0 dark:border-zinc-800">
        {parentPath && (
          <>
            <span
              className="shrink-0 max-w-[160px] truncate text-stone-400 dark:text-zinc-600"
              title={parentPath}
            >
              {parentPath}
            </span>
            <span className="text-stone-300 dark:text-zinc-700">/</span>
          </>
        )}
        <span className="font-medium text-stone-700 truncate min-w-0 dark:text-zinc-200">{fileName}</span>

        <div className="ml-auto flex items-center gap-1.5 shrink-0">
          {isReadOnly && (
            <span className="rounded bg-stone-100 px-1.5 py-px text-[9px] font-semibold uppercase tracking-wide text-stone-500 dark:bg-zinc-800 dark:text-zinc-500">
              Read only
            </span>
          )}
          {isDirty && !isReadOnly && (
            <span
              className="h-1.5 w-1.5 rounded-full bg-amber-400"
              title="Unsaved changes — Cmd+S to save"
            />
          )}
        </div>
      </div>

      {/* CodeMirror container */}
      <div ref={setContainer} className="flex-1 overflow-hidden" />
    </div>
  );
});
