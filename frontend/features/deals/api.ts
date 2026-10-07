import { API_BASE, ApiError, SERVER_DOWN_MESSAGE, apiDownload, apiFetch, errorForStatus, getToken } from "@/shared/api/client";
import type {
  AgentRun, AgentRunDetail, Condition, CreateMandateBody, Deal, DealDetail, DealParty, DealDocument, DiligenceItem, DocumentVersion,
  DealNote, Extraction, Finding, GuardResult, Mandate, Member, Party, Signoff,
} from "./types";

export const listDeals = () => apiFetch<Deal[]>("/api/deals");
export const createDeal = (b: { external_id: string; name: string; transaction_class: string }) =>
  apiFetch<Deal>("/api/deals", { method: "POST", body: b });
export const getDeal = (id: number) => apiFetch<DealDetail>(`/api/deals/${id}`);
export const patchDeal = (id: number, b: { regulatory_flags: string[] }) =>
  apiFetch<Deal>(`/api/deals/${id}`, { method: "PATCH", body: b });
export const getGuards = (id: number, to: string) =>
  apiFetch<GuardResult[]>(`/api/deals/${id}/guards?to_stage=${encodeURIComponent(to)}`);
export const transition = (
  id: number,
  b: { to_stage: string; reason_code?: string; override_justification?: string },
) => apiFetch<{ deal: Deal; evaluations: GuardResult[] }>(`/api/deals/${id}/transition`, { method: "POST", body: b });

/* ---------------------------------- Walls ---------------------------------- */

export const listMembers = (id: number) => apiFetch<Member[]>(`/api/deals/${id}/members`);
export const addMember = (id: number, username: string) =>
  apiFetch<Member[]>(`/api/deals/${id}/members`, { method: "POST", body: { username } });
export const removeMember = (id: number, username: string) =>
  apiFetch<Member[]>(`/api/deals/${id}/members`, { method: "DELETE", body: { username } });

/* -------------------------------- Compliance -------------------------------- */

export const listSignoffs = (id: number) => apiFetch<Signoff[]>(`/api/deals/${id}/signoffs`);
export const signOff = (id: number, note: string) =>
  apiFetch<Signoff>(`/api/deals/${id}/signoffs`, { method: "POST", body: { note } });

/* --------------------------------- Mandates -------------------------------- */

export const listMandates = (id: number) => apiFetch<Mandate[]>(`/api/deals/${id}/mandates`);
export const createMandate = (id: number, b: CreateMandateBody) =>
  apiFetch<Mandate>(`/api/deals/${id}/mandates`, { method: "POST", body: b });

/* ---------------------------------- Parties --------------------------------- */

export const listParties = () => apiFetch<Party[]>("/api/parties");
export const createParty = (b: {
  party_type: string;
  display_name: string;
  identifiers: { scheme: string; value: string }[];
}) => apiFetch<Party>("/api/parties", { method: "POST", body: b });
export const addDealParty = (id: number, b: { party_id: number; role: string }) =>
  apiFetch<DealParty>(`/api/deals/${id}/parties`, { method: "POST", body: b });

/* --------------------------------- Documents -------------------------------- */

export const listDocuments = (id: number) => apiFetch<DealDocument[]>(`/api/deals/${id}/documents`);
/** Reading one document's metadata is logged as a view (F5.2). */
export const getDocument = (docId: number) => apiFetch<DealDocument>(`/api/documents/${docId}`);
export const listDocumentVersions = (docId: number) => apiFetch<DocumentVersion[]>(`/api/documents/${docId}/versions`);
/** Setting doc_class also confirms it. */
export const patchDocument = (docId: number, b: { is_executed?: boolean; doc_class?: string }) =>
  apiFetch<DealDocument>(`/api/documents/${docId}`, { method: "PATCH", body: b });
export const downloadDocument = (docId: number, name: string) =>
  apiDownload(`/api/documents/${docId}/download`, name);

/* --------------------------------- Diligence -------------------------------- */

export const listDiligence = (id: number) => apiFetch<DiligenceItem[]>(`/api/deals/${id}/diligence`);
export const patchDiligence = (
  id: number,
  b: { status: string; evidence_doc_ids?: number[]; waiver_justification?: string },
) => apiFetch<DiligenceItem>(`/api/diligence/${id}`, { method: "PATCH", body: b });

export const listFindings = (id: number) => apiFetch<Finding[]>(`/api/deals/${id}/findings`);
export const createFinding = (
  id: number,
  b: { diligence_item_id: number; finding_type: string; description: string; quantified_impact_inr?: number | null; affects_valuation: boolean },
) => apiFetch<Finding>(`/api/deals/${id}/findings`, { method: "POST", body: b });

export const listConditions = (id: number) => apiFetch<Condition[]>(`/api/deals/${id}/conditions`);
export const createCondition = (id: number, b: { description: string; cp_type: string }) =>
  apiFetch<Condition>(`/api/deals/${id}/conditions`, { method: "POST", body: b });
export const patchCondition = (id: number, b: { status: string; waiver_justification?: string }) =>
  apiFetch<Condition>(`/api/conditions/${id}`, { method: "PATCH", body: b });

/* -------------------------------- Extractions ------------------------------- */

export const listExtractions = (id: number) => apiFetch<Extraction[]>(`/api/deals/${id}/extractions`);
export const verifyExtraction = (extractionId: number) =>
  apiFetch<Extraction>(`/api/extractions/${extractionId}/verify`, { method: "POST" });

/* -------------------------------- Agent runs -------------------------------- */

export const listAgentRuns = (dealId: number) => apiFetch<AgentRun[]>(`/api/agent-runs?deal_id=${dealId}`);
export const getAgentRun = (runId: number) => apiFetch<AgentRunDetail>(`/api/agent-runs/${runId}`);

/* ------------------------------ Upload (with %) ----------------------------- */

/** Upload with progress (fetch cannot report upload progress). Errors match apiFetch’s. */
export function uploadDocumentWithProgress(id: number, form: FormData, onProgress: (pct: number) => void) {
  return new Promise<DealDocument>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_BASE}/api/deals/${id}/documents`);
    const token = getToken();
    if (token) xhr.setRequestHeader("Authorization", `Bearer ${token}`);
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(Math.round((e.loaded / e.total) * 100));
    xhr.onerror = () => reject(new ApiError("network", SERVER_DOWN_MESSAGE));
    xhr.onload = () => {
      let body: unknown = null;
      try {
        body = JSON.parse(xhr.responseText);
      } catch {
        /* non-JSON */
      }
      if (xhr.status >= 200 && xhr.status < 300) return resolve(body as DealDocument);
      // 401 → auth-expired (signs out), 403 → forbidden, else the server's message.
      reject(errorForStatus(xhr.status, body, Boolean(token), `Upload failed (${xhr.status})`));
    };
    xhr.send(form);
  });
}
export const listNotes = (id: number) => apiFetch<DealNote[]>(`/api/deals/${id}/notes`);
