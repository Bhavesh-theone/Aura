"use client";

import { ArrowUpRight } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useRef } from "react";
import { cx, timeAgo } from "@/shared/lib/format";
import { useApi } from "@/shared/lib/useApi";
import { PageHeader } from "@/shared/ui/PageHeader";
import { Badge, Button } from "@/shared/ui/primitives";
import { useCrumbs } from "@/shared/ui/shell/crumbs";
import { EmptyState, InlineError, Skel, Unavailable } from "@/shared/ui/States";
import { getDocumentFormats } from "../api";
import { useIntakeWizard } from "../hooks";
import { phaseOf, stepOf, type Step } from "../machine";
import { FALLBACK_FORMATS, type DocumentFormats } from "../types";
import { STEPS, Stepper } from "./bits";
import { ConfirmStep } from "./ConfirmStep";
import { ProcessingStep } from "./ProcessingStep";
import { ReviewStep } from "./ReviewStep";
import { StartStep } from "./StartStep";

const COPY: Record<string, { title: string; description: string }> = {
  start: {
    title: "New deal",
    description: "Drop in the documents you have. Aura reads them, fills the deal in, and shows you where every value came from.",
  },
  processing: {
    title: "Reading your documents",
    description: "Each file is read, indexed and then mined for deal fields. You can leave — the draft carries on without you.",
  },
  review: {
    title: "Review the extracted deal",
    description: "Check the highlighted fields against their sources. Every edit is saved as you go.",
  },
  confirm: { title: "Create the deal", description: "One last look before it lands on the 12-stage spine." },
};

function parseId(v: string | null) {
  const n = v ? Number(v) : NaN;
  return Number.isInteger(n) && n > 0 ? n : null;
}

function WizardSkeleton() {
  return (
    <div className="px-8 pt-7" aria-busy="true" aria-label="Loading draft">
      <Skel className="h-8 w-[320px]" />
      <Skel className="mt-3 h-3 w-[480px] max-w-full" />
      <div className="mt-6 flex gap-3">
        {STEPS.map((s) => (
          <Skel key={s.id} className="h-6 w-24" />
        ))}
      </div>
      <Skel className="mt-6 h-56 w-full rounded-md" />
    </div>
  );
}

export function DealIntakeWizard() {
  const router = useRouter();
  const params = useSearchParams();
  const paramId = parseId(params.get("intake"));

  // Keep the URL resumable once a draft exists (replace: Back still leaves the wizard).
  const onCreated = useCallback((id: number) => router.replace(`/deals/new?intake=${id}`, { scroll: false }), [router]);
  const w = useIntakeWizard(paramId, onCreated);
  const formatsApi = useApi<DocumentFormats | null>(getDocumentFormats, null);
  const formats = formatsApi.data ?? FALLBACK_FORMATS;

  const s = w.state;
  const step: Step = stepOf(s);
  const phase = phaseOf(s);
  const intake = s.intake;

  useCrumbs([{ label: "Deals", href: "/deals" }, { label: intake && intake.title !== "Untitled intake" ? intake.title : "New deal" }]);

  // Focus the heading whenever the step changes so keyboard and screen-reader users follow along.
  const heading = useRef<HTMLHeadingElement>(null);
  const firstStep = useRef(true);
  useEffect(() => {
    if (firstStep.current) {
      firstStep.current = false;
      return;
    }
    heading.current?.focus({ preventScroll: true });
    document.getElementById("main-scroll")?.scrollTo({ top: 0, behavior: "smooth" });
  }, [step]);

  // Leaving with unsaved edits or uploads in flight: ask the browser to confirm.
  const dirty = phase === "uploading" || s.inflight !== null || Object.keys(s.edits.fields).length > 0;
  useEffect(() => {
    if (!dirty) return;
    const on = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", on);
    return () => window.removeEventListener("beforeunload", on);
  }, [dirty]);

  if (step === "loading") return <WizardSkeleton />;

  if (step === "gone" || step === "error") {
    return (
      <div className="px-8 pt-7">
        <PageHeader className="px-0" title="New deal" />
        <div className="max-w-xl space-y-4">
          {step === "gone" ? <Unavailable what="This draft" /> : <InlineError message={s.loadError ?? "Something went wrong."} onRetry={w.reload} />}
          <Button variant="secondary" onClick={() => router.push("/deals/new")}>Start a new deal instead</Button>
        </div>
      </div>
    );
  }

  if (step === "confirmed") {
    const dealId = s.confirmedDealId ?? intake?.confirmed_deal_id ?? null;
    return (
      <EmptyState
        title={s.confirmedDealId ? "Deal created — opening it…" : "This draft is already a deal"}
        description={s.confirmedDealId ? undefined : "It was confirmed earlier, so there’s nothing left to review here."}
        action={
          dealId ? (
            <Link href={`/deals/${dealId}`} className="inline-flex h-8 items-center gap-1.5 rounded-sm bg-accent px-3 text-[13px] font-medium text-on-accent hover:bg-accent-hover">
              Open the deal <ArrowUpRight className="h-4 w-4" />
            </Link>
          ) : undefined
        }
      />
    );
  }

  const copy = COPY[step];
  const reachable = (id: string) => {
    if (id === "start") return true;
    if (!intake) return false;
    if (id === "processing") return intake.files.length > 0 || intake.status !== "draft";
    if (id === "review") return intake.status === "review";
    return false; // confirm only through "Continue to confirm"
  };

  return (
    <div className="flex flex-1 flex-col pb-16">
      <div className="px-8 pb-5 pt-7">
        <div className="flex flex-wrap items-start gap-x-6 gap-y-3">
          <div className="min-w-0">
            <h1 ref={heading} tabIndex={-1} className="font-serif text-[28px] leading-[1.15] text-fg outline-none">
              {copy.title}
            </h1>
            <p className="mt-1.5 max-w-2xl text-[13px] text-muted">{copy.description}</p>
          </div>
          {intake ? (
            <div className="ml-auto flex items-center gap-2 text-[12px] text-muted">
              <Badge tone="neutral">Draft</Badge>
              <span className="truncate">{intake.title}</span>
              <span aria-hidden>·</span>
              <span>saved {timeAgo(intake.updated_at)}</span>
            </div>
          ) : null}
        </div>
        <div className="mt-5">
          <Stepper current={step} reachable={reachable} onGo={(id) => w.dispatch({ type: "go", view: id as "start" | "processing" | "review" })} />
        </div>
      </div>

      <div className={cx("px-8")}>
        {step === "start" ? (
          <StartStep w={w} formats={formats} />
        ) : step === "processing" ? (
          <ProcessingStep w={w} />
        ) : step === "review" ? (
          <ReviewStep w={w} onContinue={() => w.dispatch({ type: "go", view: "confirm" })} />
        ) : (
          <ConfirmStep w={w} />
        )}
      </div>
    </div>
  );
}
