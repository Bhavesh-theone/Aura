import type { User } from "./types";

export type Role = "admin" | "dealmaker" | "analyst" | "compliance";

export const ROLE_LABEL: Record<string, string> = {
  admin: "Admin",
  dealmaker: "Dealmaker",
  analyst: "Analyst",
  compliance: "Compliance",
};

export const ROLE_OPTIONS: Role[] = ["dealmaker", "analyst", "compliance", "admin"];

export const roleLabel = (r: string | null | undefined) => (r ? ROLE_LABEL[r] ?? r.charAt(0).toUpperCase() + r.slice(1) : "");

/**
 * The permission matrix the backend enforces (PRD §3). The UI uses it only to
 * hide or disable controls and to say who *can* — every action still handles
 * a 403 inline, because the server is the authority.
 */
export type Action =
  | "transition" // move a deal along the stage machine
  | "overrideTransition" // move a deal only by overriding compliance-owned guards
  | "resolveHandoff" // record a decision on a handoff (trigger-dependent, see canResolve)
  | "manageMembers" // deal wall membership
  | "signoff" // compliance sign-off on flagged deals
  | "editFlags" // regulatory flags
  | "manageUsers" // admin › users
  | "work"; // analyst work: documents, diligence, conditions, findings, parties, mandates, agent jobs

const MATRIX: Record<Action, Role[]> = {
  transition: ["dealmaker"],
  overrideTransition: ["compliance"],
  resolveHandoff: ["dealmaker"],
  manageMembers: ["compliance"],
  signoff: ["compliance"],
  editFlags: ["dealmaker", "compliance"],
  manageUsers: ["admin"],
  // EDIT_DEAL_DATA (core/policy/rbac_policy.py): dealmakers and analysts.
  work: ["analyst", "dealmaker"],
};

/** "Only dealmakers can …" — the sentence shown in tooltips and notices. */
export const WHO_CAN: Record<Action, string> = {
  transition: "Only dealmakers can move a deal between stages.",
  overrideTransition: "Compliance can only advance a deal by overriding a failing compliance guard.",
  resolveHandoff: "Only dealmakers can record decisions.",
  manageMembers: "Only compliance can change who is on a deal’s wall.",
  signoff: "Only compliance can sign off.",
  editFlags: "Only dealmakers and compliance can edit regulatory flags.",
  manageUsers: "Only admins can manage users.",
  work: "Only analysts and dealmakers can do this.",
};

export function can(user: User | null | undefined, action: Action): boolean {
  if (!user) return false;
  return (MATRIX[action] as string[]).includes(user.role);
}

/** Dealmakers resolve handoffs; compliance may also resolve policy-required ones. */
export function canResolve(user: User | null | undefined, trigger: string): boolean {
  if (!user) return false;
  if (user.role === "dealmaker") return true;
  return user.role === "compliance" && trigger === "policy_required";
}

export function whoCanResolve(trigger: string) {
  return trigger === "policy_required"
    ? "Only dealmakers or compliance can record this decision."
    : WHO_CAN.resolveHandoff;
}
