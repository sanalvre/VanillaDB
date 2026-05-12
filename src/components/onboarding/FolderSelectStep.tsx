import { useState } from "react";
import { open } from "@tauri-apps/plugin-dialog";
import { createVault } from "@/api/sidecar";
import { normalizePath } from "@/api/paths";

interface FolderSelectStepProps {
  ontologyMd: string;
  agentsMd: string;
  onComplete: (cleanPath: string, wikiPath: string) => void;
  onBack: () => void;
}

export function FolderSelectStep({
  ontologyMd,
  agentsMd,
  onComplete,
  onBack,
}: FolderSelectStepProps) {
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function pickFolder() {
    const result = await open({ directory: true, multiple: false });
    if (typeof result === "string") {
      setSelectedPath(result);
      setError(null);
    }
  }

  async function handleCreate() {
    if (!selectedPath) return;
    setCreating(true);
    setError(null);
    try {
      const normalized = normalizePath(selectedPath);
      const res = await createVault(normalized, ontologyMd, agentsMd);
      if (res.success) {
        onComplete(res.clean_vault_path, res.wiki_vault_path);
      } else {
        setError("Vault creation did not return success.");
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Vault creation failed");
    } finally {
      setCreating(false);
    }
  }

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-lg font-semibold text-stone-800">
          Choose a vault location
        </h2>
        <p className="mt-1 text-sm text-stone-500">
          Select a folder where Vanilla will create your vault. Two sub-folders
          will be created:{" "}
          <span className="font-medium text-stone-700">clean-vault/</span> for
          your source files and{" "}
          <span className="font-medium text-stone-700">wiki-vault/</span> for
          the generated knowledge wiki.
        </p>
      </div>

      {/* Folder picker */}
      <div className="rounded-md border border-dashed border-stone-300 p-6 text-center">
        {selectedPath ? (
          <div className="space-y-2">
            <p className="text-sm font-medium text-stone-700">Selected folder:</p>
            <p className="break-all rounded bg-stone-50 px-3 py-2 font-mono text-xs text-stone-600">
              {selectedPath}
            </p>
            <button
              onClick={pickFolder}
              className="mt-1 text-sm text-amber-600 underline transition hover:text-amber-500"
            >
              Change folder
            </button>
          </div>
        ) : (
          <button
            onClick={pickFolder}
            className="rounded-md bg-stone-100 px-5 py-3 text-sm font-medium text-stone-700 transition hover:bg-stone-200"
          >
            Choose a folder...
          </button>
        )}
      </div>

      {error && <p className="text-sm font-medium text-red-600">{error}</p>}

      <div className="flex gap-3 pt-2">
        <button
          onClick={onBack}
          className="rounded-md border border-stone-300 px-4 py-2.5 text-sm font-medium text-stone-700 transition hover:bg-stone-50"
        >
          Back
        </button>
        <button
          onClick={handleCreate}
          disabled={!selectedPath || creating}
          className="flex-1 rounded-md bg-amber-600 px-4 py-2.5 text-sm font-medium text-white transition hover:bg-amber-500 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {creating ? "Creating vault..." : "Create Vault"}
        </button>
      </div>
    </div>
  );
}
