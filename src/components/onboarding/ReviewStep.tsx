import { useState } from "react";

interface ReviewStepProps {
  ontologyMd: string;
  categories: string[];
  onNext: (ontologyMd: string, categories: string[]) => void;
  onBack: () => void;
}

export function ReviewStep({
  ontologyMd,
  categories: initialCategories,
  onNext,
  onBack,
}: ReviewStepProps) {
  const [content, setContent] = useState(ontologyMd);
  const [categories, setCategories] = useState<string[]>(initialCategories);
  const [editingIdx, setEditingIdx] = useState<number | null>(null);
  const [editValue, setEditValue] = useState("");

  function removeCategory(idx: number) {
    setCategories((prev) => prev.filter((_, i) => i !== idx));
  }

  function startEdit(idx: number) {
    setEditingIdx(idx);
    setEditValue(categories[idx]);
  }

  function commitEdit() {
    if (editingIdx === null) return;
    const trimmed = editValue.trim();
    if (trimmed) {
      setCategories((prev) =>
        prev.map((c, i) => (i === editingIdx ? trimmed : c)),
      );
    }
    setEditingIdx(null);
    setEditValue("");
  }

  function handleEditKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Enter") {
      e.preventDefault();
      commitEdit();
    } else if (e.key === "Escape") {
      setEditingIdx(null);
    }
  }

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-lg font-semibold text-stone-800">
          Review your ontology
        </h2>
        <p className="mt-1 text-sm text-stone-500">
          Edit the generated ontology below. You can always change this later.
        </p>
      </div>

      {/* Categories */}
      {categories.length > 0 && (
        <div>
          <label className="mb-1.5 block text-sm font-medium text-stone-700">
            Categories
          </label>
          <div className="flex flex-wrap gap-2">
            {categories.map((cat, idx) =>
              editingIdx === idx ? (
                <input
                  key={idx}
                  type="text"
                  value={editValue}
                  onChange={(e) => setEditValue(e.target.value)}
                  onBlur={commitEdit}
                  onKeyDown={handleEditKeyDown}
                  autoFocus
                  className="rounded-full border border-amber-400 bg-amber-50 px-3 py-1 text-xs text-stone-800 focus:outline-none focus:ring-1 focus:ring-amber-500"
                />
              ) : (
                <span
                  key={idx}
                  className="group flex items-center gap-1 rounded-full bg-stone-100 px-3 py-1 text-xs font-medium text-stone-700"
                >
                  <span
                    className="cursor-pointer"
                    onClick={() => startEdit(idx)}
                    title="Click to edit"
                  >
                    {cat}
                  </span>
                  <button
                    onClick={() => removeCategory(idx)}
                    className="ml-0.5 text-stone-400 transition hover:text-red-500"
                    title="Remove category"
                  >
                    x
                  </button>
                </span>
              ),
            )}
          </div>
        </div>
      )}

      {/* Ontology content */}
      <div>
        <label className="mb-1.5 block text-sm font-medium text-stone-700">
          Ontology
        </label>
        <textarea
          value={content}
          onChange={(e) => setContent(e.target.value)}
          rows={12}
          className="w-full resize-y rounded-md border border-stone-300 px-3 py-2 font-mono text-sm text-stone-800 focus:border-amber-500 focus:outline-none focus:ring-1 focus:ring-amber-500"
        />
      </div>

      <div className="flex gap-3 pt-2">
        <button
          onClick={onBack}
          className="rounded-md border border-stone-300 px-4 py-2.5 text-sm font-medium text-stone-700 transition hover:bg-stone-50"
        >
          Back
        </button>
        <button
          onClick={() => onNext(content, categories)}
          className="flex-1 rounded-md bg-amber-600 px-4 py-2.5 text-sm font-medium text-white transition hover:bg-amber-500"
        >
          Looks good
        </button>
      </div>
    </div>
  );
}
