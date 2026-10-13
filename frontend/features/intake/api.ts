import { API_BASE, ApiError, SERVER_DOWN_MESSAGE, apiFetch, errorForStatus, getToken } from "@/shared/api/client";
import type {
  ConfirmResult, DocumentFormats, Intake, IntakeChunk, IntakeHints, IntakePatch, IntakeSummary, UploadResult,
} from "./types";

export const createIntake = (b: Partial<IntakeHints>) => apiFetch<Intake>("/api/intakes", { method: "POST", body: b });
export const listIntakes = () => apiFetch<IntakeSummary[]>("/api/intakes");
export const getIntake = (id: number) => apiFetch<Intake>(`/api/intakes/${id}`);
export const patchIntake = (id: number, b: IntakePatch) =>
  apiFetch<Intake>(`/api/intakes/${id}`, { method: "PATCH", body: b });
export const deleteIntakeFile = (id: number, fileId: number) =>
  apiFetch<Intake>(`/api/intakes/${id}/files/${fileId}`, { method: "DELETE" });
/** Re-run extraction (it also starts by itself once every file is indexed). 202. */
export const extractIntake = (id: number) => apiFetch<Intake>(`/api/intakes/${id}/extract`, { method: "POST" });
export const getIntakeChunk = (id: number, chunkId: number) =>
  apiFetch<IntakeChunk>(`/api/intakes/${id}/chunks/${chunkId}`);
export const confirmIntake = (id: number, b: { external_id?: string; name?: string }) =>
  apiFetch<ConfirmResult>(`/api/intakes/${id}/confirm`, { method: "POST", body: b, timeoutMs: 30000 });
export const discardIntake = (id: number) => apiFetch<void>(`/api/intakes/${id}`, { method: "DELETE" });
export const getDocumentFormats = () => apiFetch<DocumentFormats>("/api/document-formats");

/**
 * One file, one request, with upload progress (fetch can't report it).
 * Errors match apiFetch's (413 / 415 come back as ApiError "http" with the
 * server's detail). Returns an abort function alongside the promise.
 */
export function uploadIntakeFile(id: number, file: File, onProgress: (pct: number) => void) {
  const xhr = new XMLHttpRequest();
  const promise = new Promise<UploadResult>((resolve, reject) => {
    xhr.open("POST", `${API_BASE}/api/intakes/${id}/files`);
    const token = getToken();
    if (token) xhr.setRequestHeader("Authorization", `Bearer ${token}`);
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(Math.round((e.loaded / e.total) * 100));
    xhr.onerror = () => reject(new ApiError("network", SERVER_DOWN_MESSAGE));
    xhr.onabort = () => reject(new ApiError("network", "Upload cancelled."));
    xhr.onload = () => {
      let body: unknown = null;
      try {
        body = JSON.parse(xhr.responseText);
      } catch {
        /* non-JSON */
      }
      if (xhr.status >= 200 && xhr.status < 300) return resolve(body as UploadResult);
      reject(errorForStatus(xhr.status, body, Boolean(token), `Upload failed (${xhr.status})`));
    };
    const form = new FormData();
    form.append("files", file);
    xhr.send(form);
  });
  return { promise, abort: () => xhr.abort() };
}
