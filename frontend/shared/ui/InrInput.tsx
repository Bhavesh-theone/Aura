"use client";

import { cx, formatINR, formatINRCompact } from "@/shared/lib/format";
import { Segmented, inputCls } from "./primitives";

export type InrUnit = "inr" | "lakh" | "crore";
const FACTOR: Record<InrUnit, number> = { inr: 1, lakh: 1e5, crore: 1e7 };

/** Parse "1,25,000" or "4.5" in the chosen unit → whole rupees (null when blank/invalid). */
export function toRupees(text: string, unit: InrUnit): number | null {
  const n = Number(text.replace(/[,\s₹]/g, ""));
  if (!text.trim() || !Number.isFinite(n)) return null;
  return Math.round(n * FACTOR[unit]);
}

/**
 * Amount in rupees with a ₹ / L / Cr unit switch and a live en-IN readback
 * ("= ₹4.5 Cr · ₹4,50,00,000") so nobody fat-fingers a crore for a lakh.
 */
export function InrInput({
  id,
  text,
  unit,
  onText,
  onUnit,
  invalid,
  disabled,
  emptyHint = "Leave blank if the impact can’t be quantified yet.",
}: {
  id: string;
  text: string;
  unit: InrUnit;
  onText: (v: string) => void;
  onUnit: (u: InrUnit) => void;
  invalid?: boolean;
  disabled?: boolean;
  /** Readback line while the field is blank. */
  emptyHint?: string;
}) {
  const rupees = toRupees(text, unit);
  const bad = text.trim() !== "" && rupees === null;
  return (
    <div>
      <div className="flex gap-2">
        <div className="relative flex-1">
          <span className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-[13px] text-muted">₹</span>
          <input
            id={id}
            inputMode="decimal"
            value={text}
            disabled={disabled}
            onChange={(e) => onText(e.target.value)}
            aria-invalid={bad || invalid || undefined}
            aria-describedby={`${id}-readback`}
            className={cx(inputCls, "num pl-6 font-mono", (bad || invalid) && "border-danger focus:border-danger")}
            placeholder={unit === "crore" ? "4.5" : unit === "lakh" ? "18.5" : "86,400"}
          />
        </div>
        <Segmented
          label="Unit"
          value={unit}
          onChange={onUnit}
          options={[
            { value: "inr", label: "₹", title: "Rupees" },
            { value: "lakh", label: "L", title: "Lakh (1,00,000)" },
            { value: "crore", label: "Cr", title: "Crore (1,00,00,000)" },
          ]}
        />
      </div>
      <p id={`${id}-readback`} className={cx("mt-1.5 text-[12px]", bad ? "text-danger" : "text-muted")}>
        {bad ? "Enter a number, e.g. 4.5" : rupees !== null ? (
          <>
            = <span className="num font-medium text-fg-2">{formatINRCompact(rupees)}</span>
            <span className="num font-mono"> · {formatINR(rupees)}</span>
          </>
        ) : (
          emptyHint
        )}
      </p>
    </div>
  );
}
