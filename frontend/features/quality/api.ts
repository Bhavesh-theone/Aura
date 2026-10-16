import { apiFetch } from "@/shared/api/client";
import type { Autonomy, EvalRun, EvalRunDetail, OverrideRate, PromptEntry } from "./types";

export const listAutonomy = () => apiFetch<Autonomy[]>("/api/autonomy");
export const promote = (capability: string) =>
  apiFetch<Autonomy>(`/api/autonomy/${encodeURIComponent(capability)}/promote`, { method: "POST" });
export const listEvalRuns = (limit = 100) => apiFetch<EvalRun[]>(`/api/evals/runs?limit=${limit}`);
export const getEvalRun = (id: number) => apiFetch<EvalRunDetail>(`/api/evals/runs/${id}`);
export const listOverrideRates = () => apiFetch<OverrideRate[]>("/api/evals/override-rates");
export const listPrompts = () => apiFetch<PromptEntry[]>("/api/prompts");
