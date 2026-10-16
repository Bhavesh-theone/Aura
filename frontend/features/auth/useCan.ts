"use client";

import { useCallback } from "react";
import { useAuth } from "./hooks";
import { can, type Action } from "./roles";

/** `const allowed = useCan(); allowed("work")` — role checks bound to the signed-in user. */
export function useCan() {
  const { user } = useAuth();
  return useCallback((action: Action) => can(user, action), [user]);
}
