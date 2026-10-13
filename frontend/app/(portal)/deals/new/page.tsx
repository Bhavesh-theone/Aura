import { Suspense } from "react";
import { DealIntakeWizard } from "@/features/intake";

export default function NewDealPage() {
  // The wizard reads ?intake= (useSearchParams) — client-rendered below this boundary.
  return (
    <Suspense fallback={null}>
      <DealIntakeWizard />
    </Suspense>
  );
}
