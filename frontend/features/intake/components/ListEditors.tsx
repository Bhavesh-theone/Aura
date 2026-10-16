"use client";

import { Plus, X } from "lucide-react";
import { cx, humanize, titleCase } from "@/shared/lib/format";
import { IconButton, inputCls, selectCls } from "@/shared/ui/primitives";
import {
  FLAGS, HARDNESS, ID_SCHEMES, OPERATORS, PARTY_ROLES, PARTY_TYPES, type CriterionValue, type FlagValue, type PartyValue,
} from "../types";
import type { InputProps } from "./FieldInput";

const sm = "h-7 text-[12px]";

function asList<T>(v: unknown): T[] {
  return Array.isArray(v) ? (v as T[]) : [];
}

/** Shared row chrome: include toggle on the left, remove on the right; excluded rows fade. */
function ItemRow({
  include,
  onInclude,
  onRemove,
  label,
  children,
}: {
  include: boolean;
  onInclude: (v: boolean) => void;
  onRemove: () => void;
  label: string;
  children: React.ReactNode;
}) {
  return (
    <li className={cx("flex items-start gap-2.5 rounded-sm border border-line-subtle bg-canvas px-2.5 py-2", !include && "opacity-60")}>
      <input
        type="checkbox"
        checked={include}
        onChange={(e) => onInclude(e.target.checked)}
        aria-label={`Include ${label}`}
        title={include ? "Included — untick to leave it out of the deal" : "Left out — tick to include"}
        className="mt-1.5 h-3.5 w-3.5 shrink-0"
      />
      <div className="min-w-0 flex-1">{children}</div>
      <IconButton size="sm" label={`Remove ${label}`} onClick={onRemove} className="mt-0.5">
        <X className="h-3.5 w-3.5" />
      </IconButton>
    </li>
  );
}

function AddButton({ onClick, children, id }: { onClick: () => void; children: React.ReactNode; id?: string }) {
  return (
    <button
      type="button"
      id={id}
      onClick={onClick}
      className="inline-flex h-7 items-center gap-1 rounded-sm px-1.5 text-[12px] font-medium text-fg-2 hover:bg-control-hover hover:text-fg"
    >
      <Plus className="h-3.5 w-3.5" /> {children}
    </button>
  );
}

function Select({ value, options, onChange, label, labels }: { value: string; options: readonly string[]; onChange: (v: string) => void; label: string; labels?: (o: string) => string }) {
  const opts = value && !options.includes(value) ? [value, ...options] : options;
  return (
    <select aria-label={label} value={value} onChange={(e) => onChange(e.target.value)} className={cx(selectCls, sm, "w-auto")}>
      {opts.map((o) => (
        <option key={o} value={o}>{labels ? labels(o) : o}</option>
      ))}
    </select>
  );
}

/* --------------------------------- Parties -------------------------------- */

export function PartiesEditor({ field, id, onChange, describedBy }: InputProps) {
  const list = asList<PartyValue>(field.value);
  const set = (i: number, patch: Partial<PartyValue>) => onChange(list.map((p, j) => (j === i ? { ...p, ...patch } : p)));
  return (
    <div role="group" aria-labelledby={`${id}-label`} aria-describedby={describedBy}>
      {list.length ? (
        <ul className="space-y-1.5">
          {list.map((p, i) => {
            const name = p.name || `party ${i + 1}`;
            const ids = p.identifiers ?? [];
            return (
              <ItemRow key={i} label={name} include={p.include !== false} onInclude={(include) => set(i, { include })} onRemove={() => onChange(list.filter((_, j) => j !== i))}>
                <div className="flex flex-wrap items-center gap-1.5">
                  <input
                    id={i === 0 ? id : undefined}
                    aria-label={`Party ${i + 1} name`}
                    value={p.name ?? ""}
                    onChange={(e) => set(i, { name: e.target.value })}
                    className={cx(inputCls, sm, "min-w-[180px] flex-1")}
                    placeholder="Name"
                  />
                  <Select label={`${name} role`} value={p.role ?? ""} options={PARTY_ROLES} labels={titleCase} onChange={(role) => set(i, { role })} />
                  <Select label={`${name} type`} value={p.party_type ?? ""} options={PARTY_TYPES} labels={humanize} onChange={(party_type) => set(i, { party_type })} />
                </div>
                {ids.length ? (
                  <ul className="mt-1.5 space-y-1">
                    {ids.map((x, k) => (
                      <li key={k} className="flex items-center gap-1.5">
                        <Select
                          label={`${name} identifier ${k + 1} scheme`}
                          value={x.scheme}
                          options={ID_SCHEMES}
                          onChange={(scheme) => set(i, { identifiers: ids.map((y, m) => (m === k ? { ...y, scheme } : y)) })}
                        />
                        <input
                          aria-label={`${name} ${x.scheme} value`}
                          value={x.value}
                          spellCheck={false}
                          onChange={(e) => set(i, { identifiers: ids.map((y, m) => (m === k ? { ...y, value: e.target.value.toUpperCase() } : y)) })}
                          className={cx(inputCls, sm, "flex-1 font-mono")}
                        />
                        <IconButton size="sm" label={`Remove ${x.scheme}`} onClick={() => set(i, { identifiers: ids.filter((_, m) => m !== k) })}>
                          <X className="h-3 w-3" />
                        </IconButton>
                      </li>
                    ))}
                  </ul>
                ) : null}
                <AddButton onClick={() => set(i, { identifiers: [...ids, { scheme: "CIN", value: "" }] })}>Identifier</AddButton>
              </ItemRow>
            );
          })}
        </ul>
      ) : (
        <p className="text-[12px] text-muted">No parties found in the documents.</p>
      )}
      <AddButton id={list.length ? undefined : id} onClick={() => onChange([...list, { name: "", role: "target", party_type: "company", identifiers: [], include: true }])}>
        Add party
      </AddButton>
    </div>
  );
}

/* -------------------------------- Criteria -------------------------------- */

const show = (v: unknown) => (v === null || v === undefined ? "" : typeof v === "string" ? v : JSON.stringify(v));
const readBack = (t: string): unknown => {
  const s = t.trim();
  if (!s) return null;
  if (/^-?\d+(\.\d+)?$/.test(s)) return Number(s);
  if (s.startsWith("[") || s.startsWith("{")) {
    try {
      return JSON.parse(s);
    } catch {
      return s;
    }
  }
  return s;
};

export function CriteriaEditor({ field, id, onChange, describedBy }: InputProps) {
  const list = asList<CriterionValue>(field.value);
  const set = (i: number, patch: Partial<CriterionValue>) => onChange(list.map((c, j) => (j === i ? { ...c, ...patch } : c)));
  return (
    <div role="group" aria-labelledby={`${id}-label`} aria-describedby={describedBy}>
      {list.length ? (
        <ul className="space-y-1.5">
          {list.map((c, i) => {
            const name = c.criterion_key ? humanize(c.criterion_key) : `criterion ${i + 1}`;
            return (
              <ItemRow key={i} label={name} include={c.include !== false} onInclude={(include) => set(i, { include })} onRemove={() => onChange(list.filter((_, j) => j !== i))}>
                <div className="flex flex-wrap items-center gap-1.5">
                  <input
                    id={i === 0 ? id : undefined}
                    aria-label={`Criterion ${i + 1} key`}
                    value={c.criterion_key ?? ""}
                    onChange={(e) => set(i, { criterion_key: e.target.value })}
                    className={cx(inputCls, sm, "w-40 font-mono")}
                    placeholder="criterion_key"
                  />
                  <Select label={`${name} operator`} value={c.operator ?? "eq"} options={OPERATORS} onChange={(operator) => set(i, { operator })} />
                  <input
                    aria-label={`${name} value`}
                    defaultValue={show(c.value)}
                    onBlur={(e) => set(i, { value: readBack(e.target.value) })}
                    className={cx(inputCls, sm, "min-w-[120px] flex-1 font-mono")}
                    placeholder={c.operator === "between" ? "[min, max]" : "value"}
                  />
                  <Select
                    label={`${name} hardness`}
                    value={c.hardness ?? "hard"}
                    options={HARDNESS}
                    labels={titleCase}
                    onChange={(hardness) => set(i, { hardness, weight: hardness === "soft" ? (c.weight ?? 0.5) : c.weight })}
                  />
                  {c.hardness === "soft" ? (
                    <input
                      aria-label={`${name} weight (0 to 1)`}
                      type="number"
                      min={0}
                      max={1}
                      step={0.05}
                      value={c.weight ?? ""}
                      onChange={(e) => set(i, { weight: e.target.value === "" ? null : Number(e.target.value) })}
                      className={cx(inputCls, sm, "num w-20 font-mono")}
                      title="Weight, 0–1"
                    />
                  ) : null}
                </div>
              </ItemRow>
            );
          })}
        </ul>
      ) : (
        <p className="text-[12px] text-muted">No mandate criteria proposed.</p>
      )}
      <AddButton
        id={list.length ? undefined : id}
        onClick={() => onChange([...list, { criterion_key: "", operator: "eq", value: null, hardness: "hard", weight: null, include: true }])}
      >
        Add criterion
      </AddButton>
    </div>
  );
}

/* ---------------------------------- Flags --------------------------------- */

export function FlagsEditor({ field, id, onChange, describedBy }: InputProps) {
  const list = asList<FlagValue>(field.value);
  const set = (i: number, patch: Partial<FlagValue>) => onChange(list.map((f, j) => (j === i ? { ...f, ...patch } : f)));
  const unused = FLAGS.filter((f) => !list.some((x) => x.flag === f));
  return (
    <div role="group" aria-labelledby={`${id}-label`} aria-describedby={describedBy}>
      {list.length ? (
        <ul className="space-y-1.5">
          {list.map((f, i) => (
            <ItemRow key={i} label={`${f.flag} flag`} include={f.include !== false} onInclude={(include) => set(i, { include })} onRemove={() => onChange(list.filter((_, j) => j !== i))}>
              <div className="flex flex-wrap items-center gap-1.5">
                <Select label={`Flag ${i + 1}`} value={f.flag} options={FLAGS} labels={(o) => o.replace(/_/g, " ")} onChange={(flag) => set(i, { flag })} />
                <input
                  id={i === 0 ? id : undefined}
                  aria-label={`${f.flag} reason`}
                  value={f.reason ?? ""}
                  onChange={(e) => set(i, { reason: e.target.value })}
                  className={cx(inputCls, sm, "min-w-[200px] flex-1")}
                  placeholder="Why this approval applies"
                />
              </div>
            </ItemRow>
          ))}
        </ul>
      ) : (
        <p className="text-[12px] text-muted">No regulatory approvals flagged.</p>
      )}
      {unused.length ? (
        <AddButton id={list.length ? undefined : id} onClick={() => onChange([...list, { flag: unused[0], reason: "", include: true }])}>
          Add flag
        </AddButton>
      ) : null}
    </div>
  );
}
