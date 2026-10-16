export type Span = {
  trace_id: string;
  span_id: string;
  parent_span_id: string | null;
  name: string;
  start: string;
  end: string | null;
  duration_ms: number | null;
  attributes: Record<string, unknown>;
  status: string;
};

export type TraceResponse = { trace_id: string; spans: Span[] };
