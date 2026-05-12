import { useState } from "react";
import { ApiKeyStep, type LLMConfig } from "./ApiKeyStep";
import { DescriptionStep } from "./DescriptionStep";
import { GeneratingStep } from "./GeneratingStep";
import { ReviewStep } from "./ReviewStep";
import { FolderSelectStep } from "./FolderSelectStep";
import type { GenerateOntologyResponse } from "@/api/onboarding";

const TOTAL_STEPS = 5;

interface OnboardingFlowProps {
  onComplete: (cleanPath: string, wikiPath: string) => void;
}

export function OnboardingFlow({ onComplete }: OnboardingFlowProps) {
  const [currentStep, setCurrentStep] = useState(0);
  const [llmConfig, setLlmConfig] = useState<LLMConfig | undefined>();
  const [description, setDescription] = useState<string | undefined>();
  const [ontologyResult, setOntologyResult] = useState<GenerateOntologyResponse | undefined>();
  const [editedOntology, setEditedOntology] = useState<string | undefined>();
  const [editedCategories, setEditedCategories] = useState<string[] | undefined>();

  function renderStep() {
    switch (currentStep) {
      case 0:
        return (
          <ApiKeyStep
            initial={llmConfig}
            onNext={(config) => {
              setLlmConfig(config);
              setCurrentStep(1);
            }}
          />
        );
      case 1:
        return (
          <DescriptionStep
            initial={description}
            onNext={(desc) => {
              setDescription(desc);
              setCurrentStep(2);
            }}
            onBack={() => setCurrentStep(0)}
          />
        );
      case 2:
        return (
          <GeneratingStep
            description={description!}
            llmConfig={llmConfig!}
            onComplete={(result) => {
              setOntologyResult(result);
              setEditedOntology(result.ontology_md);
              setEditedCategories(result.suggested_categories);
              setCurrentStep(3);
            }}
            onBack={() => setCurrentStep(1)}
          />
        );
      case 3:
        return (
          <ReviewStep
            ontologyMd={editedOntology ?? ontologyResult!.ontology_md}
            categories={editedCategories ?? ontologyResult!.suggested_categories}
            onNext={(md, cats) => {
              setEditedOntology(md);
              setEditedCategories(cats);
              setCurrentStep(4);
            }}
            onBack={() => setCurrentStep(1)}
          />
        );
      case 4:
        return (
          <FolderSelectStep
            ontologyMd={editedOntology ?? ontologyResult!.ontology_md}
            agentsMd={ontologyResult!.agents_md}
            onComplete={onComplete}
            onBack={() => setCurrentStep(3)}
          />
        );
      default:
        return null;
    }
  }

  return (
    <div className="flex flex-1 items-center justify-center p-4">
      <div className="w-full max-w-lg">
        {/* Step indicator dots */}
        <div className="mb-6 flex items-center justify-center gap-2">
          {Array.from({ length: TOTAL_STEPS }, (_, i) => (
            <div
              key={i}
              className={`h-2 w-2 rounded-full transition-colors ${
                i === currentStep
                  ? "bg-amber-600"
                  : i < currentStep
                    ? "bg-amber-300"
                    : "bg-stone-300"
              }`}
            />
          ))}
        </div>

        {/* Step card */}
        <div className="rounded-xl border border-stone-200 bg-white p-6 shadow-sm">
          {renderStep()}
        </div>
      </div>
    </div>
  );
}
