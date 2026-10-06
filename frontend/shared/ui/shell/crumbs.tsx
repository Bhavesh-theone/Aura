"use client";

import { createContext, useContext, useEffect } from "react";

export type Crumb = { label: string; href?: string };

export const CrumbContext = createContext<(c: Crumb[] | null) => void>(() => {});

/** Pages call this to extend the top-bar breadcrumb (e.g. a deal's name). */
export function useCrumbs(crumbs: Crumb[] | null) {
  const set = useContext(CrumbContext);
  const key = JSON.stringify(crumbs);
  useEffect(() => {
    set(crumbs);
    return () => set(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, set]);
}
