/**
 * FileTree — recursive file browser with right-click context menu.
 *
 * Operations available per node:
 *   File nodes: Rename (inline), Delete (→ _trash/), Reveal in Explorer
 *   Directory nodes: Reveal in Explorer
 *
 * New file creation: "+" button in the panel header, creates in the
 * directory of the currently selected file (or clean-vault/raw/ as fallback).
 *
 * All mutations call the FastAPI sidecar then force a tree refresh.
 */

import {
  useEffect, useRef, useState, useCallback, memo,
} from "react";
import {
  getVaultFiles,
  deleteVaultFile,
  renameVaultFile,
  createVaultFile,
  revealInExplorer,
  type FileTreeNode,
} from "@/api/sidecar";
import { useEditorStore } from "@/stores/editorStore";
import { useGraphStore } from "@/stores/graphStore";

/* ─── Icons ──────────────────────────────────────────────────────── */

function FolderIcon({ open }: { open: boolean }) {
  return (
    <svg width="13" height="13" viewBox="0 0 16 16" fill="none" className="shrink-0 text-stone-400 dark:text-zinc-600">
      <path
        d={open ? "M1.5 3.5h5l1 1.5H14.5v8h-13z" : "M1.5 3h5l1 1.5H14.5v8.5h-13z"}
        stroke="currentColor" strokeWidth="1.2"
        fill={open ? "currentColor" : "none"} fillOpacity={open ? "0.12" : "0"}
      />
    </svg>
  );
}

function FileIcon({ active }: { active: boolean }) {
  return (
    <svg width="13" height="13" viewBox="0 0 16 16" fill="none" className="shrink-0">
      <path d="M4 1.5h5.5L13 5v9.5H4z"
        stroke={active ? "#78716c" : "#d6d3d1"} strokeWidth="1.2" fill="none" />
      <path d="M9.5 1.5V5H13" stroke={active ? "#78716c" : "#d6d3d1"} strokeWidth="1.2" />
    </svg>
  );
}

function PlusIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
      <path d="M6 1v10M1 6h10" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
    </svg>
  );
}

/* ─── Loading skeleton ───────────────────────────────────────────── */

function TreeSkeleton() {
  return (
    <div className="space-y-1 px-2 py-1 animate-pulse">
      {[80, 60, 90, 50, 70].map((w, i) => (
        <div key={i} className="h-5 rounded bg-stone-100 dark:bg-zinc-800"
          style={{ width: `${w}%`, marginLeft: i > 1 ? "12px" : "0" }} />
      ))}
    </div>
  );
}

/* ─── Context menu ───────────────────────────────────────────────── */

interface ContextMenuState {
  x: number;
  y: number;
  node: FileTreeNode;
}

function ContextMenu({
  menu,
  onRename,
  onDelete,
  onReveal,
  onClose,
}: {
  menu: ContextMenuState;
  onRename: () => void;
  onDelete: () => void;
  onReveal: () => void;
  onClose: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleKey(e: KeyboardEvent) { if (e.key === "Escape") onClose(); }
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose();
    }
    document.addEventListener("keydown", handleKey);
    document.addEventListener("mousedown", handleClick);
    return () => {
      document.removeEventListener("keydown", handleKey);
      document.removeEventListener("mousedown", handleClick);
    };
  }, [onClose]);

  const isFile = menu.node.type === "file";
  const item = "flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-xs text-stone-700 hover:bg-stone-100 dark:text-zinc-300 dark:hover:bg-zinc-700 disabled:opacity-40 transition-colors";

  return (
    <div
      ref={ref}
      style={{ position: "fixed", top: menu.y, left: menu.x, zIndex: 9999 }}
      className="min-w-[140px] rounded-lg border border-stone-200 bg-white py-1 shadow-lg dark:border-zinc-700 dark:bg-zinc-800"
    >
      {isFile && (
        <>
          <button className={item} onClick={() => { onClose(); onRename(); }}>
            <svg width="11" height="11" viewBox="0 0 12 12" fill="none">
              <path d="M8.5 1.5l2 2-7 7H1.5v-2l7-7z" stroke="currentColor" strokeWidth="1.2" strokeLinejoin="round" />
            </svg>
            Rename
          </button>
          <button className={`${item} text-red-600 hover:bg-red-50 dark:text-red-400 dark:hover:bg-red-950/30`}
            onClick={() => { onClose(); onDelete(); }}>
            <svg width="11" height="11" viewBox="0 0 12 12" fill="none">
              <path d="M2 3h8M4 3V2h4v1M5 5v4M7 5v4M3 3l.5 7h5l.5-7H3z" stroke="currentColor" strokeWidth="1.1" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            Delete
          </button>
          <div className="my-1 border-t border-stone-100 dark:border-zinc-700" />
        </>
      )}
      <button className={item} onClick={() => { onClose(); onReveal(); }}>
        <svg width="11" height="11" viewBox="0 0 12 12" fill="none">
          <rect x="1" y="2" width="10" height="8" rx="1" stroke="currentColor" strokeWidth="1.1" />
          <path d="M1 5h10" stroke="currentColor" strokeWidth="1.1" />
          <path d="M4 2V1M8 2V1" stroke="currentColor" strokeWidth="1.1" strokeLinecap="round" />
        </svg>
        Reveal in Explorer
      </button>
    </div>
  );
}

/* ─── Inline rename input ────────────────────────────────────────── */

function RenameInput({
  initialName,
  onConfirm,
  onCancel,
}: {
  initialName: string;
  onConfirm: (name: string) => void;
  onCancel: () => void;
}) {
  // Strip .md for editing comfort; we'll re-add it in onConfirm
  const bare = initialName.endsWith(".md") ? initialName.slice(0, -3) : initialName;
  const [value, setValue] = useState(bare);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    inputRef.current?.select();
  }, []);

  function commit() {
    const trimmed = value.trim();
    if (trimmed && trimmed !== bare) onConfirm(trimmed);
    else onCancel();
  }

  return (
    <input
      ref={inputRef}
      value={value}
      onChange={(e) => setValue(e.target.value)}
      onKeyDown={(e) => {
        if (e.key === "Enter") { e.preventDefault(); commit(); }
        if (e.key === "Escape") { e.preventDefault(); onCancel(); }
      }}
      onBlur={commit}
      className="w-full rounded border border-amber-400 bg-white px-1 py-0 text-xs text-stone-800 outline-none dark:bg-zinc-900 dark:text-zinc-200"
      onClick={(e) => e.stopPropagation()}
    />
  );
}

/* ─── Tree node ──────────────────────────────────────────────────── */

const TreeNode = memo(function TreeNode({
  node,
  depth,
  activePath,
  renamingPath,
  onSelect,
  onContextMenu,
  onRenameConfirm,
  onRenameCancel,
}: {
  node: FileTreeNode;
  depth: number;
  activePath: string | null;
  renamingPath: string | null;
  onSelect: (path: string) => void;
  onContextMenu: (e: React.MouseEvent, node: FileTreeNode) => void;
  onRenameConfirm: (path: string, newName: string) => void;
  onRenameCancel: () => void;
}) {
  const [expanded, setExpanded] = useState(depth < 1);
  const isDir = node.type === "directory";
  const isActive = node.path === activePath;
  const isRenaming = node.path === renamingPath;
  const indent = depth * 12 + 4;

  if (isDir) {
    return (
      <div>
        <button
          onContextMenu={(e) => { e.preventDefault(); onContextMenu(e, node); }}
          onClick={() => setExpanded((v) => !v)}
          aria-expanded={expanded}
          className="flex w-full items-center gap-1.5 rounded px-1 py-[3px] text-left text-xs
                     text-stone-500 transition-colors hover:bg-stone-100 hover:text-stone-700
                     dark:text-zinc-400 dark:hover:bg-zinc-800 dark:hover:text-zinc-200
                     focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-amber-400"
          style={{ paddingLeft: `${indent}px` }}
        >
          <FolderIcon open={expanded} />
          <span className="truncate font-medium">{node.name}</span>
        </button>
        {expanded && node.children.map((child) => (
          <TreeNode
            key={child.path}
            node={child}
            depth={depth + 1}
            activePath={activePath}
            renamingPath={renamingPath}
            onSelect={onSelect}
            onContextMenu={onContextMenu}
            onRenameConfirm={onRenameConfirm}
            onRenameCancel={onRenameCancel}
          />
        ))}
      </div>
    );
  }

  return (
    <div
      onContextMenu={(e) => { e.preventDefault(); onContextMenu(e, node); }}
      style={{ paddingLeft: `${indent}px` }}
      className={`flex w-full items-center gap-1.5 rounded px-1 py-[3px] text-xs
                  transition-colors focus-within:ring-1 focus-within:ring-amber-400
                  ${isActive
                    ? "bg-stone-200 text-stone-900 font-medium dark:bg-zinc-700 dark:text-zinc-100"
                    : "text-stone-500 hover:bg-stone-50 hover:text-stone-700 dark:text-zinc-400 dark:hover:bg-zinc-800 dark:hover:text-zinc-200"
                  }`}
    >
      <FileIcon active={isActive} />
      {isRenaming ? (
        <RenameInput
          initialName={node.name}
          onConfirm={(name) => onRenameConfirm(node.path, name)}
          onCancel={onRenameCancel}
        />
      ) : (
        <button
          onClick={() => onSelect(node.path)}
          aria-current={isActive ? "page" : undefined}
          title={node.path}
          className="min-w-0 flex-1 truncate text-left focus-visible:outline-none"
        >
          {node.name}
        </button>
      )}
    </div>
  );
});

/* ─── New file inline form ───────────────────────────────────────── */

function NewFileInput({
  onConfirm,
  onCancel,
}: {
  onConfirm: (name: string) => void;
  onCancel: () => void;
}) {
  const [value, setValue] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  useEffect(() => { inputRef.current?.focus(); }, []);

  function commit() {
    const trimmed = value.trim();
    if (trimmed) onConfirm(trimmed);
    else onCancel();
  }

  return (
    <div className="flex items-center gap-1 border-b border-stone-100 px-2 py-1.5 dark:border-zinc-700">
      <svg width="11" height="11" viewBox="0 0 12 12" fill="none" className="shrink-0 text-stone-400">
        <path d="M7 1H3a1 1 0 0 0-1 1v8a1 1 0 0 0 1 1h6a1 1 0 0 0 1-1V5L7 1Z"
          stroke="currentColor" strokeWidth="1.2" strokeLinejoin="round" />
        <path d="M7 1v4h4" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      <input
        ref={inputRef}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") { e.preventDefault(); commit(); }
          if (e.key === "Escape") { e.preventDefault(); onCancel(); }
        }}
        onBlur={onCancel}
        placeholder="filename.md"
        className="flex-1 bg-transparent text-xs text-stone-800 placeholder:text-stone-300 outline-none dark:text-zinc-200 dark:placeholder:text-zinc-600"
      />
      <span className="text-[10px] text-stone-300 dark:text-zinc-600">↵</span>
    </div>
  );
}

/* ─── FileTree container ─────────────────────────────────────────── */

export const FileTree = memo(function FileTree() {
  const [tree, setTree] = useState<FileTreeNode[]>([]);
  const [loading, setLoading] = useState(true);
  const [contextMenu, setContextMenu] = useState<ContextMenuState | null>(null);
  const [renamingPath, setRenamingPath] = useState<string | null>(null);
  const [creatingFile, setCreatingFile] = useState(false);
  const [opError, setOpError] = useState<string | null>(null);

  const activePath = useEditorStore((s) => s.activeFilePath);
  const openFile = useEditorStore((s) => s.openFile);
  const closeFile = useEditorStore((s) => s.closeFile);

  const lastTreeHash = useRef<string | null>(null);
  const failCount = useRef(0);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const refresh = useCallback(async () => {
    try {
      const data = await getVaultFiles();
      failCount.current = 0;
      if (data.tree_hash !== lastTreeHash.current) {
        lastTreeHash.current = data.tree_hash ?? null;
        setTree(data.tree);
      }
    } catch {
      failCount.current++;
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    function schedule() {
      const delay = failCount.current > 0
        ? Math.min(120_000, 30_000 * Math.pow(2, failCount.current - 1))
        : 30_000;
      intervalRef.current = setTimeout(() => { refresh().then(schedule); }, delay);
    }
    schedule();
    return () => { if (intervalRef.current) clearTimeout(intervalRef.current); };
  }, [refresh]);

  // Derive a sensible default directory for new files
  const defaultNewFileDir = activePath
    ? activePath.includes("/")
      ? activePath.substring(0, activePath.lastIndexOf("/"))
      : "clean-vault/raw"
    : "clean-vault/raw";

  /* ── Context menu handlers ── */
  const handleContextMenu = useCallback((e: React.MouseEvent, node: FileTreeNode) => {
    e.stopPropagation();
    setContextMenu({ x: e.clientX, y: e.clientY, node });
    setOpError(null);
  }, []);

  /* ── Delete ── */
  async function handleDelete(node: FileTreeNode) {
    if (!window.confirm(`Move "${node.name}" to trash?`)) return;
    try {
      await deleteVaultFile(node.path);
      // If the deleted file is currently open, close it
      if (activePath === node.path) await closeFile();
      useGraphStore.getState().fetchGraph();
      // Force tree refresh by clearing hash
      lastTreeHash.current = null;
      await refresh();
    } catch (e) {
      setOpError(e instanceof Error ? e.message : "Delete failed");
    }
  }

  /* ── Rename ── */
  async function handleRenameConfirm(path: string, newName: string) {
    setRenamingPath(null);
    try {
      const result = await renameVaultFile(path, newName);
      // Reopen if it was the active file
      if (activePath === path) await openFile(result.new_path);
      useGraphStore.getState().fetchGraph();
      lastTreeHash.current = null;
      await refresh();
    } catch (e) {
      setOpError(e instanceof Error ? e.message : "Rename failed");
    }
  }

  /* ── New file ── */
  async function handleNewFileConfirm(name: string) {
    setCreatingFile(false);
    const safeName = name.endsWith(".md") ? name : `${name}.md`;
    const path = `${defaultNewFileDir}/${safeName}`;
    try {
      const result = await createVaultFile(path, `# ${safeName.replace(".md", "")}\n\n`);
      lastTreeHash.current = null;
      await refresh();
      await openFile(result.path);
    } catch (e) {
      setOpError(e instanceof Error ? e.message : "Create failed");
    }
  }

  /* ── Reveal ── */
  async function handleReveal(node: FileTreeNode) {
    try {
      await revealInExplorer(node.path);
    } catch (e) {
      setOpError(e instanceof Error ? e.message : "Could not open explorer");
    }
  }

  if (loading) return <TreeSkeleton />;

  return (
    <div className="flex flex-col">
      {/* Panel header */}
      <div className="flex items-center justify-between px-1 pb-1 pt-0.5">
        <span className="text-[10px] font-semibold uppercase tracking-wider text-stone-400 dark:text-zinc-500">
          Files
        </span>
        <button
          onClick={() => { setCreatingFile(true); setOpError(null); }}
          title="New file"
          className="rounded p-0.5 text-stone-400 hover:bg-stone-100 hover:text-stone-600 dark:text-zinc-500 dark:hover:bg-zinc-800 dark:hover:text-zinc-300 transition-colors"
        >
          <PlusIcon />
        </button>
      </div>

      {/* New file input (appears below header) */}
      {creatingFile && (
        <NewFileInput
          onConfirm={handleNewFileConfirm}
          onCancel={() => setCreatingFile(false)}
        />
      )}

      {/* Error banner */}
      {opError && (
        <div className="mb-1 rounded border border-red-100 bg-red-50 px-2 py-1 text-[10px] text-red-600 dark:border-red-900/40 dark:bg-red-950/20 dark:text-red-400">
          {opError}
          <button className="ml-2 opacity-60 hover:opacity-100" onClick={() => setOpError(null)}>✕</button>
        </div>
      )}

      {/* Tree */}
      {tree.length === 0 ? (
        <div className="px-3 py-4 text-center">
          <p className="text-xs text-stone-400 dark:text-zinc-600">No files yet</p>
          <p className="mt-1 text-[11px] text-stone-300 dark:text-zinc-700">
            Click + to create your first file
          </p>
        </div>
      ) : (
        <div className="flex flex-col gap-px py-1">
          {tree.map((node) => (
            <TreeNode
              key={node.path}
              node={node}
              depth={0}
              activePath={activePath}
              renamingPath={renamingPath}
              onSelect={openFile}
              onContextMenu={handleContextMenu}
              onRenameConfirm={handleRenameConfirm}
              onRenameCancel={() => setRenamingPath(null)}
            />
          ))}
        </div>
      )}

      {/* Context menu (portal-style fixed positioning) */}
      {contextMenu && (
        <ContextMenu
          menu={contextMenu}
          onClose={() => setContextMenu(null)}
          onRename={() => setRenamingPath(contextMenu.node.path)}
          onDelete={() => handleDelete(contextMenu.node)}
          onReveal={() => handleReveal(contextMenu.node)}
        />
      )}
    </div>
  );
});
