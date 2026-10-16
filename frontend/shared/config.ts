/**
 * The firm's display name — set NEXT_PUBLIC_FIRM_NAME in .env.local.
 * Used by the sidebar, page metadata and the sign-in page; nowhere else
 * should hard-code a firm.
 */
export const FIRM_NAME = process.env.NEXT_PUBLIC_FIRM_NAME?.trim() || "Aura";

/** "Aura · Deal desk" reads oddly as "Aura · Aura", so the subtitle adapts. */
export const PRODUCT_LINE = FIRM_NAME === "Aura" ? "Deal desk" : "Aura · Deal desk";
