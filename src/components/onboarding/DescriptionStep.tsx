import { useState } from "react";

interface DescriptionStepProps {
  initial?: string;
  onNext: (description: string) => void;
  onBack: () => void;
}

const MIN_CHARS = 20;

export function DescriptionStep({ initial, onNext, onBack }: DescriptionStepProps) {
  const [description, setDescription] = useState(initial ?? "");

  const charCount = description.trim().length;
  const canContinue = charCount >= MIN_CHARS;

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-lg font-semibold text-stone-800">
          Describe your vault
        </h2>
        <p className="mt-1 text-sm text-stone-500">
          Tell Vanilla what kind of knowledge you will store. This helps generate
          a useful ontology for organizing your wiki.
        </p>
      </div>

      <div>
        <label className="mb-1.5 block text-sm font-medium text-stone-700">
          What is this vault for?
        </label>
        <textarea
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          rows={6}
          placeholder={`Examples:\n- "My personal research on machine learning and AI safety"\n- "Company engineering knowledge base covering backend services, deployment, and incident runbooks"\n- "Recipe collection organized by cuisine and dietary restrictions"`}
          className="w-full resize-none rounded-md border border-stone-300 px-3 py-2 text-sm text-stone-800 placeholder:text-stone-400 focus:border-amber-500 focus:outline-none focus:ring-1 focus:ring-amber-500"
        />
        <p className="mt-1 text-xs text-stone-400">
          {charCount} / {MIN_CHARS} minimum characters
        </p>
      </div>

      <div className="flex gap-3 pt-2">
        <button
          onClick={onBack}
          className="rounded-md border border-stone-300 px-4 py-2.5 text-sm font-medium text-stone-700 transition hover:bg-stone-50"
        >
          Back
        </button>
        <button
          onClick={() => onNext(description.trim())}
          disabled={!canContinue}
          className="flex-1 rounded-md bg-amber-600 px-4 py-2.5 text-sm font-medium text-white transition hover:bg-amber-500 disabled:cursor-not-allowed disabled:opacity-50"
        >
          Continue
        </button>
      </div>
    </div>
  );
}
