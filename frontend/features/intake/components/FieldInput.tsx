"use client";

import { Plus, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { cx } from "@/shared/lib/format";
import { InrInput, toRupees, type InrUnit } from "@/shared/ui/InrInput";
import { IconButton, Segmented, inputCls, selectCls, textareaCls } from "@/shared/ui/primitives";
import type { IntakeField } from "../types";
import { CriteriaEditor, FlagsEditor, PartiesEditor } from "./ListEditors";

export type InputProps = {
  field: IntakeField;
  id: string;
  onChange: (value: unknown) => void;
  invalid?: boolean;
  describedBy?: string;
};

/**
 * Text state that follows the value from outside unless the user is mid-edit
 * (e.g. "11." while typing 11.25 must not snap back to "11").
 */
function useDraftText(value: unknown, format: (v: unknown) => string, parse: (t: string) => unknown) {
  const [text, setText] = useState(() => format(value));
  const last = useRef(value);
  useEffect(() => {
    if (value === last.current) return;
    last.current = value;
    // Only overwrite when the outside value differs from what the text means.
    if (JSON.stringify(parse(text)) !== JSON.stringify(value)) setText(format(value));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);
  return [text, (t: string) => { setText(t); last.current = parse(t); return last.current; }] as const;
}

const str = (v: unknown) => (v === null || v === undefined ? "" : typeof v === "string" ? v : String(v));

function NumberInput({ field, id, onChange, invalid, describedBy }: InputProps) {
  const integer = field.type === "integer";
  const parse = (t: string): number | null => {
    const s = t.replace(/[,\s%]/g, "");
    if (!s) return null;
    const n = Number(s);
    return Number.isFinite(n) ? (integer ? Math.trunc(n) : n) : NaN;
  };
  const [text, setText] = useDraftText(field.value, (v) => (typeof v === "number" ? String(v) : str(v)), parse);
  const parsed = parse(text);
  const bad = parsed !== null && Number.isNaN(parsed);
  return (
    <div className="relative">
      <input
        id={id}
        inputMode={integer ? "numeric" : "decimal"}
        value={text}
        aria-invalid={bad || invalid || undefined}
        aria-describedby={describedBy}
        onChange={(e) => {
          const v = setText(e.target.value);
          if (!(typeof v === "number" && Number.isNaN(v))) onChange(v);
        }}
        className={cx(inputCls, "num font-mono", field.type === "percent" && "pr-7", (bad || invalid) && "border-danger focus:border-danger")}
      />
      {field.type === "percent" ? <span className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 text-[13px] text-muted">%</span> : null}
      {bad ? <p className="mt-1 text-[12px] text-danger">Enter a number{integer ? " (whole)" : ""}.</p> : null}
    </div>
  );
}

function bestUnit(v: unknown): InrUnit {
  if (typeof v !== "number") return "crore";
  const a = Math.abs(v);
  return a >= 1e7 ? "crore" : a >= 1e5 ? "lakh" : "inr";
}
const FACTOR: Record<InrUnit, number> = { inr: 1, lakh: 1e5, crore: 1e7 };
const inUnit = (v: unknown, unit: InrUnit) =>
  typeof v === "number" ? String(Number((v / FACTOR[unit]).toFixed(unit === "inr" ? 0 : 4))) : "";

function MoneyInput({ field, id, onChange, invalid }: InputProps) {
  const [unit, setUnit] = useState<InrUnit>(() => bestUnit(field.value));
  const [text, setText] = useState(() => inUnit(field.value, unit));
  useEffect(() => {
    // Follow outside changes (refetch, revert) unless the text already means this value.
    if (toRupees(text, unit) !== (typeof field.value === "number" ? field.value : null)) {
      const u = bestUnit(field.value);
      setUnit(u);
      setText(inUnit(field.value, u));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [field.value]);
  return (
    <InrInput
      id={id}
      text={text}
      unit={unit}
      invalid={invalid}
      emptyHint="Whole rupees. Switch to L or Cr to type in lakh or crore."
      onText={(t) => {
        setText(t);
        const r = toRupees(t, unit);
        if (r !== null || !t.trim()) onChange(r);
      }}
      onUnit={(u) => {
        // Keep the amount, change how it's typed.
        const r = toRupees(text, unit);
        setUnit(u);
        if (r !== null) setText(inUnit(r, u));
      }}
    />
  );
}

function StringList({ field, id, onChange, describedBy }: InputProps) {
  const items = Array.isArray(field.value) ? (field.value as unknown[]).map(str) : [];
  return (
    <div className="space-y-1.5" role="group" aria-labelledby={`${id}-label`} aria-describedby={describedBy}>
      {items.map((it, i) => (
        <div key={i} className="flex items-center gap-1.5">
          <input
            id={i === 0 ? id : undefined}
            aria-label={`${field.label} ${i + 1}`}
            value={it}
            onChange={(e) => onChange(items.map((x, j) => (j === i ? e.target.value : x)))}
            className={inputCls}
          />
          <IconButton size="sm" label={`Remove ${field.label} ${i + 1}`} onClick={() => onChange(items.filter((_, j) => j !== i))}>
            <X className="h-3.5 w-3.5" />
          </IconButton>
        </div>
      ))}
      <button
        type="button"
        id={items.length === 0 ? id : undefined}
        onClick={() => onChange([...items, ""])}
        className="inline-flex h-7 items-center gap-1 rounded-sm px-1.5 text-[12px] font-medium text-fg-2 hover:bg-control-hover hover:text-fg"
      >
        <Plus className="h-3.5 w-3.5" /> Add
      </button>
    </div>
  );
}

function JsonInput({ field, id, onChange, invalid, describedBy }: InputProps) {
  const [text, setText] = useState(() => JSON.stringify(field.value ?? null, null, 2));
  const [bad, setBad] = useState(false);
  return (
    <div>
      <textarea
        id={id}
        value={text}
        spellCheck={false}
        aria-invalid={bad || invalid || undefined}
        aria-describedby={describedBy}
        onChange={(e) => {
          setText(e.target.value);
          try {
            onChange(JSON.parse(e.target.value));
            setBad(false);
          } catch {
            setBad(true);
          }
        }}
        className={cx(textareaCls, "font-mono text-[12px]", (bad || invalid) && "border-danger")}
      />
      {bad ? <p className="mt-1 text-[12px] text-danger">Not valid JSON yet — not saved.</p> : null}
    </div>
  );
}

export function FieldInput(props: InputProps) {
  const { field, id, onChange, invalid, describedBy } = props;
  const common = {
    id,
    "aria-invalid": invalid || undefined,
    "aria-describedby": describedBy,
  };
  const err = invalid && "border-danger focus:border-danger";
  switch (field.type) {
    case "inr":
      return <MoneyInput {...props} />;
    case "number":
    case "integer":
    case "percent":
      return <NumberInput {...props} />;
    case "textarea":
      return <textarea {...common} value={str(field.value)} onChange={(e) => onChange(e.target.value)} className={cx(textareaCls, err)} />;
    case "date":
      return <input {...common} type="date" value={str(field.value)} onChange={(e) => onChange(e.target.value || null)} className={cx(inputCls, "num w-auto min-w-[160px]", err)} />;
    case "enum":
      return (
        <select {...common} value={str(field.value)} onChange={(e) => onChange(e.target.value || null)} className={cx(selectCls, err)}>
          <option value="">—</option>
          {str(field.value) && !(field.options ?? []).includes(str(field.value)) ? <option value={str(field.value)}>{str(field.value)}</option> : null}
          {(field.options ?? []).map((o) => (
            <option key={o} value={o}>{field.enum_labels?.[o] ?? o}</option>
          ))}
        </select>
      );
    case "boolean":
      return (
        <Segmented
          label={field.label}
          value={field.value === true ? "yes" : field.value === false ? "no" : "unset"}
          onChange={(v) => onChange(v === "yes" ? true : v === "no" ? false : null)}
          options={[
            { value: "yes", label: "Yes" },
            { value: "no", label: "No" },
            { value: "unset", label: "Unknown" },
          ]}
        />
      );
    case "identifier":
      return (
        <input
          {...common}
          value={str(field.value)}
          spellCheck={false}
          autoComplete="off"
          onChange={(e) => onChange(e.target.value.toUpperCase())}
          className={cx(inputCls, "font-mono", err)}
        />
      );
    case "string_list":
      return <StringList {...props} />;
    case "parties":
      return <PartiesEditor {...props} />;
    case "criteria":
      return <CriteriaEditor {...props} />;
    case "flags":
      return <FlagsEditor {...props} />;
    case "json":
      return <JsonInput {...props} />;
    case "text":
    default:
      return <input {...common} value={str(field.value)} onChange={(e) => onChange(e.target.value)} className={cx(inputCls, err)} />;
  }
}
