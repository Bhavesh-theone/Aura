"use client";

import { useApi } from "@/shared/lib/useApi";
import { getEvalRun, listAutonomy, listEvalRuns, listOverrideRates, listPrompts } from "./api";

export const useAutonomy = () => useApi(listAutonomy, [], []);
export const useEvalRuns = () => useApi(() => listEvalRuns(100), [], []);
export const useOverrideRates = () => useApi(listOverrideRates, [], []);
export const usePrompts = () => useApi(listPrompts, [], []);
export const useEvalRun = (id: number | null) => useApi(id === null ? null : () => getEvalRun(id), null, [id]);
