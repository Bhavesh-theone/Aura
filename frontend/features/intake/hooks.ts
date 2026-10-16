"use client";

import { useCallback, useEffect, useReducer, useRef } from "react";
import { ApiError } from "@/shared/api/client";
import { useEvents, type LiveFilter } from "@/shared/api/events";
import { eventSocket } from "@/shared/api/ws";
import { errMessage } from "@/shared/lib/useApi";
import {
  confirmIntake, createIntake, deleteIntakeFile, extractIntake, getIntake, patchIntake, uploadIntakeFile,
} from "./api";
import { hasUnsaved, initialState, isEmptyPending, reducer, toPatchBody, type Pending, type UploadItem } from "./machine";
import type { DocumentFormats, IntakeHints } from "./types";

/** Live-update cadence while the server is still working on a draft. */
const POLL_MS = 3000;
const SAVE_DEBOUNCE_MS = 600;
const SAVE_BACKOFF_MS = 5000;

const num = (v: unknown) => (typeof v === "number" ? v : typeof v === "string" && v !== "" ? Number(v) : null);

/** Socket filter: something on intake `id` changed (or, without an id, any intake). */
export const intakeEvents =
  (id?: number): LiveFilter =>
  (e) =>
    e.type === "entity_changed" && e.payload.kind === "intake" && (id === undefined || num(e.payload.intake_id) === id);

export const fileExt = (name: string) => {
  const i = name.lastIndexOf(".");
  return i >= 0 ? name.slice(i).toLowerCase() : "";
};

export function formatBytes(n?: number | null) {
  if (n == null) return "";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

function uploadMessage(err: unknown, formats: DocumentFormats): { message: string; retriable: boolean } {
  if (err instanceof ApiError && err.status === 415) {
    return { message: `Unsupported file type. Allowed: ${formats.extensions.join(", ")}.`, retriable: false };
  }
  if (err instanceof ApiError && err.status === 413) {
    return { message: `Too large — the limit is ${formats.max_upload_mb} MB.`, retriable: false };
  }
  if (err instanceof ApiError && err.kind === "network") return { message: "Connection lost during upload.", retriable: true };
  const forbidden = err instanceof ApiError && (err.kind === "forbidden" || err.kind === "auth");
  return { message: errMessage(err), retriable: !forbidden };
}

let seq = 0;
const localId = () => `u${Date.now().toString(36)}${(seq++).toString(36)}`;

/**
 * Everything the wizard does against the server: load + live refresh (socket,
 * 3 s polling while busy), lazy creation, per-file uploads, debounced
 * optimistic autosave, extraction and confirmation.
 */
export function useIntakeWizard(paramId: number | null, onCreated: (id: number) => void) {
  const [state, dispatch] = useReducer(reducer, paramId, initialState);
  const ref = useRef(state);
  ref.current = state;
  const files = useRef(new Map<string, File>());
  const aborts = useRef(new Map<string, () => void>());
  const creating = useRef<Promise<number> | null>(null);
  /** Id we just created — its URL replace() must not be mistaken for a resume. */
  const createdId = useRef<number | null>(null);
  /** Bumped by every acknowledged write; a GET that started before one is stale. */
  const epoch = useRef(0);
  const onCreatedRef = useRef(onCreated);
  onCreatedRef.current = onCreated;
  const { connection, resync } = useEvents();
  const id = state.intakeId;

  const load = useCallback((intakeId: number) => {
    const started = epoch.current;
    getIntake(intakeId)
      .then((intake) => {
        if (ref.current.intakeId !== intakeId || epoch.current !== started) return;
        dispatch({ type: "loaded", intake });
      })
      .catch((err) => {
        if (ref.current.intakeId !== intakeId) return;
        // A blip on a background refresh keeps what we have.
        if (ref.current.intake && err instanceof ApiError && (err.kind === "network" || err.kind === "timeout")) return;
        if (err instanceof ApiError && err.kind === "auth") return;
        dispatch({ type: "loadFailed", message: errMessage(err), unavailable: err instanceof ApiError && err.status === 404 });
      });
  }, []);

  // URL → state. A different ?intake= resumes that draft; the param going away
  // (e.g. "New deal" pressed while here) starts over. Our own replace() after
  // lazily creating a draft is a no-op because the ids already match.
  const prevParam = useRef(paramId);
  useEffect(() => {
    const prev = prevParam.current;
    prevParam.current = paramId;
    if (paramId !== null && paramId !== ref.current.intakeId && paramId !== createdId.current) {
      creating.current = null;
      dispatch({ type: "resume", id: paramId });
      load(paramId);
    } else if (paramId === null && prev !== null) {
      creating.current = null;
      createdId.current = null;
      files.current.clear();
      dispatch({ type: "reset" });
    } else if (paramId !== null && !ref.current.intake) {
      load(paramId);
    }
  }, [paramId, load]);

  // Socket: refetch on this intake's entity_changed (debounced).
  useEffect(() => {
    if (id === null) return;
    const match = intakeEvents(id);
    let timer: ReturnType<typeof setTimeout> | null = null;
    const off = eventSocket.onEvent((e) => {
      if (!match(e)) return;
      if (timer) clearTimeout(timer);
      timer = setTimeout(() => load(id), 200);
    });
    return () => {
      off();
      if (timer) clearTimeout(timer);
    };
  }, [id, load]);

  // Missed events while disconnected → refetch once.
  const firstResync = useRef(resync);
  useEffect(() => {
    if (id !== null && resync !== firstResync.current) load(id);
  }, [resync, id, load]);

  // Fallback polling while the server is still working.
  const status = state.intake?.status;
  const stage = state.intake?.progress.stage;
  const busy = status === "processing" || (status === "draft" && (stage === "indexing" || stage === "extracting"));
  const filesPending = state.intake?.files.some((f) => f.stage === "uploaded" || f.stage === "parsing") ?? false;
  useEffect(() => {
    if (id === null || connection === "offline" || !(busy || filesPending)) return;
    const t = setInterval(() => load(id), POLL_MS);
    return () => clearInterval(t);
  }, [id, busy, filesPending, connection, load]);

  /* -------------------------------- Autosave -------------------------------- */

  const flush = useCallback(() => {
    const s = ref.current;
    if (s.intakeId === null || s.inflight || isEmptyPending(s.edits)) return;
    const intakeId = s.intakeId;
    const body = toPatchBody(s.edits);
    dispatch({ type: "flushStart" });
    patchIntake(intakeId, body)
      .then((intake) => {
        epoch.current += 1;
        dispatch({ type: "flushOk", intake });
        // The class rebuilds the profile field set; read it back fully.
        if (body.transaction_class !== undefined) load(intakeId);
      })
      .catch((err) => dispatch({ type: "flushFail", message: errMessage(err) }));
  }, [load]);

  useEffect(() => {
    if (id === null || state.inflight || isEmptyPending(state.edits)) return;
    const delay = state.edits.transaction_class !== undefined ? 0 : state.save === "error" ? SAVE_BACKOFF_MS : SAVE_DEBOUNCE_MS;
    const t = setTimeout(flush, delay);
    return () => clearTimeout(t);
  }, [id, state.edits, state.inflight, state.save, flush]);

  const edit = useCallback((patch: Partial<Pending>) => dispatch({ type: "edit", patch }), []);

  /** Resolve once every edit is acknowledged (or reject if a save fails). */
  const settle = useCallback(async () => {
    for (let i = 0; i < 150; i++) {
      const s = ref.current;
      if (!hasUnsaved(s)) return;
      if (s.save === "error" && !s.inflight) throw new Error(s.saveError ?? "Couldn’t save your changes.");
      if (!s.inflight) flush();
      await new Promise((r) => setTimeout(r, 100));
    }
    throw new Error("Still saving — try again in a moment.");
  }, [flush]);

  /* --------------------------------- Create -------------------------------- */

  const ensureIntake = useCallback((hints?: Partial<IntakeHints>) => {
    const s = ref.current;
    if (s.intakeId !== null) return Promise.resolve(s.intakeId);
    if (!creating.current) {
      const body = { ...s.edits.hints, ...hints };
      const clean = Object.fromEntries(Object.entries(body).filter(([, v]) => v !== null && v !== undefined && String(v).trim() !== ""));
      creating.current = createIntake(clean)
        .then((intake) => {
          createdId.current = intake.id;
          dispatch({ type: "created", intake });
          onCreatedRef.current(intake.id);
          return intake.id;
        })
        .catch((err) => {
          creating.current = null;
          throw err;
        });
    }
    return creating.current;
  }, []);

  /* --------------------------------- Uploads -------------------------------- */

  const formatsRef = useRef<DocumentFormats | null>(null);

  const startUpload = useCallback(
    async (lid: string) => {
      const file = files.current.get(lid);
      const formats = formatsRef.current;
      if (!file || !formats) return;
      dispatch({ type: "progress", localId: lid, pct: 0 });
      try {
        const intakeId = await ensureIntake();
        const { promise, abort } = uploadIntakeFile(intakeId, file, (pct) => dispatch({ type: "progress", localId: lid, pct }));
        aborts.current.set(lid, abort);
        const res = await promise;
        epoch.current += 1;
        const uploaded = res.files.find((f) => f.filename === file.name) ?? res.files[0];
        dispatch({ type: "uploaded", localId: lid, file: uploaded, intake: res.intake });
        if (!uploaded?.duplicate) files.current.delete(lid);
      } catch (err) {
        if (!files.current.has(lid)) return; // removed while uploading
        const { message, retriable } = uploadMessage(err, formats);
        dispatch({ type: "uploadFailed", localId: lid, message, retriable });
      } finally {
        aborts.current.delete(lid);
      }
    },
    [ensureIntake],
  );

  const addFiles = useCallback(
    (list: FileList | File[], formats: DocumentFormats) => {
      formatsRef.current = formats;
      const maxBytes = formats.max_upload_mb * 1024 * 1024;
      const items: UploadItem[] = [];
      const valid: string[] = [];
      for (const f of Array.from(list)) {
        const lid = localId();
        let error: string | null = null;
        if (formats.extensions.length && !formats.extensions.includes(fileExt(f.name))) {
          error = `Unsupported type (${fileExt(f.name) || "no extension"}). Allowed: ${formats.extensions.join(", ")}.`;
        } else if (f.size > maxBytes) {
          error = `${formatBytes(f.size)} — the limit is ${formats.max_upload_mb} MB.`;
        } else if (f.size === 0) {
          error = "This file is empty.";
        }
        items.push({ localId: lid, name: f.name, size: f.size, status: error ? "invalid" : "queued", pct: 0, error, retriable: false });
        if (!error) {
          files.current.set(lid, f);
          valid.push(lid);
        }
      }
      dispatch({ type: "queue", items });
      valid.forEach((lid) => void startUpload(lid));
    },
    [startUpload],
  );

  const retryUpload = useCallback(
    (lid: string) => {
      dispatch({ type: "retryUpload", localId: lid });
      void startUpload(lid);
    },
    [startUpload],
  );

  const removeUpload = useCallback((lid: string) => {
    files.current.delete(lid);
    aborts.current.get(lid)?.();
    dispatch({ type: "removeUpload", localId: lid });
  }, []);

  const removeFile = useCallback(async (fileId: number) => {
    const intakeId = ref.current.intakeId;
    if (intakeId === null) return;
    const intake = await deleteIntakeFile(intakeId, fileId);
    epoch.current += 1;
    dispatch({ type: "loaded", intake });
  }, []);

  /* ------------------------------ Extract/confirm ---------------------------- */

  const extract = useCallback(async () => {
    const intakeId = await ensureIntake();
    const intake = await extractIntake(intakeId);
    epoch.current += 1;
    dispatch({ type: "loaded", intake });
  }, [ensureIntake]);

  const confirm = useCallback(
    async (body: { external_id?: string; name?: string }) => {
      const intakeId = ref.current.intakeId;
      if (intakeId === null) throw new Error("Nothing to confirm yet.");
      await settle();
      const res = await confirmIntake(intakeId, body);
      dispatch({ type: "confirmed", dealId: res.deal_id });
      return res;
    },
    [settle],
  );

  const reload = useCallback(() => {
    const intakeId = ref.current.intakeId;
    if (intakeId !== null) load(intakeId);
  }, [load]);

  return {
    state,
    dispatch,
    edit,
    flush,
    reload,
    ensureIntake,
    addFiles,
    retryUpload,
    removeUpload,
    removeFile,
    extract,
    confirm,
  };
}

export type IntakeWizard = ReturnType<typeof useIntakeWizard>;
