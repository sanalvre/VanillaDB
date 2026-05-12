import { useEffect, useState } from "react";
import { generateOntology, type GenerateOntologyResponse } from "@/api/onboarding";
import type { LLMConfig } from "./ApiKeyStep";

interface GeneratingStepProps {
  description: string;
  llmConfig: LLMConfig;
  onComplete: (result: GenerateOntologyResponse) => void;
  onBack: () => void;
}

export function GeneratingStep({
  description,
  llmConfig,
  onComplete,
  onBack,
}: GeneratingStepProps) {
  const [error, setError] = useState<string | null>(null);
  const [retryCount, setRetryCount] = useState(0);

  useEffect(() => {
    let cancelled = false;

    async function generate() {
      setError(null);
      try {
        const result = await generateOntology(
          description,
          llmConfig.provider,
          llmConfig.model,
          llmConfig.apiKey,
          llmConfig.baseUrl,
        );
        if (!cancelled) {
          onComplete(result);
        }
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "Ontology generation failed");
        }
      }
    }

    generate();

    return () => {
      cancelled = true;
    };
    // retryCount triggers re-run
  }, [description, llmConfig, retryCount]); // eslint-disable-line react-hooks/exhaustive-deps

  if (error) {
    return (
      <div className="space-y-5">
        <div>
          <h2 className="text-lg font-semibold text-stone-800">
            Generation failed
          </h2>
          <p className="mt-2 text-sm text-red-600">{error}</p>
        </div>
        <div className="flex gap-3 pt-2">
          <button
            onClick={onBack}
            className="rounded-md border border-stone-300 px-4 py-2.5 text-sm font-medium text-stone-700 transition hover:bg-stone-50"
          >
            Back
          </button>
          <button
            onClick={() => setRetryCount((c) => c + 1)}
            className="flex-1 rounded-md bg-amber-600 px-4 py-2.5 text-sm font-medium text-white transition hover:bg-amber-500"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-lg font-semibold text-stone-800">
          Generating your knowledge ontology...
        </h2>
        <p className="mt-1 text-sm text-stone-500">
          The LLM is analyzing your description and creating a tailored ontology
          for your vault. This usually takes 10-30 seconds.
        </p>
      </div>

      <div className="flex items-center justify-center py-8">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-stone-300 border-t-amber-600" />
      </div>
    </div>
  );
}
