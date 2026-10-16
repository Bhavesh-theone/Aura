import { TraceView } from "@/features/traces/components/TraceView";

export default async function TracePage({ params }: { params: Promise<{ traceId: string }> }) {
  const { traceId } = await params;
  return <TraceView traceId={traceId} />;
}
