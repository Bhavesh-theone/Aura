"use client";

import { PageHeader } from "@/shared/ui/PageHeader";
import { AutonomySection } from "./AutonomySection";
import { EvalRunsSection } from "./EvalRunsSection";
import { OverrideSection } from "./OverrideSection";
import { PromptsSection } from "./PromptsSection";

export function QualityWorkspace() {
  return (
    <div className="pb-16">
      <PageHeader
        title="Agent quality"
        description="How well each agent capability performs, how much freedom it has earned, and which prompts it runs."
      />
      <div className="space-y-9 px-4 sm:px-8">
        <AutonomySection />
        <EvalRunsSection />
        <OverrideSection />
        <PromptsSection />
      </div>
    </div>
  );
}
