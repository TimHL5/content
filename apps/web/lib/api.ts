import type {
  AssetWithUrls,
  ErrorEnvelope,
  HealthOut,
  JobAccepted,
  JobOut,
  ReferenceOut,
  UploadCompleteOut,
  UploadCreateOut,
} from "@stylecut/schemas";

export const API_URL = (
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1"
).replace(/\/$/, "");

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly hint: string | null = null,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

function isErrorEnvelope(value: unknown): value is ErrorEnvelope {
  if (typeof value !== "object" || value === null || !("error" in value)) return false;
  const error = (value as { error: unknown }).error;
  return (
    typeof error === "object" &&
    error !== null &&
    typeof (error as { code?: unknown }).code === "string" &&
    typeof (error as { message?: unknown }).message === "string"
  );
}

/** Turns a non-2xx response body into an ApiError, whatever shape it has. */
export function toApiError(status: number, body: unknown): ApiError {
  if (isErrorEnvelope(body)) {
    return new ApiError(status, body.error.code, body.error.message, body.error.hint ?? null);
  }
  return new ApiError(status, `HTTP_${status}`, `Request failed (${status}).`);
}

async function readJson(res: Response): Promise<unknown> {
  try {
    return await res.json();
  } catch {
    return null;
  }
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  const body = await readJson(res);
  if (!res.ok) throw toApiError(res.status, body);
  return body as T;
}

/** 503 still carries a HealthOut body (which dependency is down), so it is not an error here. */
export async function fetchHealth(): Promise<HealthOut> {
  const res = await fetch(`${API_URL}/health`, { cache: "no-store" });
  const body = await readJson(res);
  if (res.ok || res.status === 503) return body as HealthOut;
  throw toApiError(res.status, body);
}

export function getJob(id: string): Promise<JobOut> {
  return apiFetch<JobOut>(`/jobs/${id}`);
}

/** Local dev only: needs ENABLE_DEV_ROUTES=true on the API. */
export function startDemoJob(): Promise<JobAccepted> {
  return apiFetch<JobAccepted>("/dev/demo-job", {
    method: "POST",
    body: JSON.stringify({ seconds: 5, steps: 10 }),
  });
}

export type UploadKind = "reference" | "music" | "sfx";

export function createUpload(file: File, kind: UploadKind): Promise<UploadCreateOut> {
  return apiFetch<UploadCreateOut>("/uploads", {
    method: "POST",
    body: JSON.stringify({ filename: file.name, size: file.size, content_type: file.type, kind }),
  });
}

export function completeUpload(
  assetId: string,
  uploadId: string,
  parts: { part_number: number; etag: string }[],
): Promise<UploadCompleteOut> {
  return apiFetch<UploadCompleteOut>(`/uploads/${assetId}/complete`, {
    method: "POST",
    body: JSON.stringify({ upload_id: uploadId, parts }),
  });
}

export function createReference(source: { url: string } | { asset_id: string }): Promise<JobAccepted> {
  return apiFetch<JobAccepted>("/references", { method: "POST", body: JSON.stringify(source) });
}

export function getReference(id: string): Promise<ReferenceOut> {
  return apiFetch<ReferenceOut>(`/references/${id}`);
}

export function getAsset(id: string): Promise<AssetWithUrls> {
  return apiFetch<AssetWithUrls>(`/assets/${id}`);
}
