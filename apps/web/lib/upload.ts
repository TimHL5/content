import { ApiError, completeUpload, createUpload, type UploadKind } from "@/lib/api";

export const REFERENCE_EXTENSIONS = [".mp4", ".mov", ".m4v", ".webm"] as const;
export const REFERENCE_MAX_BYTES = 200 * 1024 * 1024;

export interface PartRange {
  partNumber: number;
  start: number;
  end: number; // exclusive
}

/** Byte ranges for a multipart upload. Part numbers start at 1. */
export function planParts(size: number, partSize: number): PartRange[] {
  if (size <= 0 || partSize <= 0) return [];
  const parts: PartRange[] = [];
  for (let start = 0, n = 1; start < size; start += partSize, n += 1) {
    parts.push({ partNumber: n, start, end: Math.min(start + partSize, size) });
  }
  return parts;
}

/** Returns a user-facing problem with the file, or null if it can be uploaded as a reference. */
export function referenceFileProblem(file: { name: string; size: number }): { message: string; hint: string } | null {
  const name = file.name.toLowerCase();
  if (!REFERENCE_EXTENSIONS.some((ext) => name.endsWith(ext))) {
    return { message: "That file type isn't supported.", hint: "Use MP4, MOV, M4V, or WebM." };
  }
  if (file.size > REFERENCE_MAX_BYTES) {
    return { message: "That file is larger than 200 MB.", hint: "Export a smaller copy and try again." };
  }
  if (file.size === 0) {
    return { message: "That file is empty.", hint: "Pick a different file." };
  }
  return null;
}

/** PUT one part straight to storage. XHR (not fetch) because it reports upload progress. */
function putPart(url: string, body: Blob, onBytes: (sent: number) => void): Promise<string> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", url);
    xhr.upload.onprogress = (e) => onBytes(e.loaded);
    xhr.onload = () => {
      const etag = xhr.getResponseHeader("ETag");
      if (xhr.status >= 200 && xhr.status < 300 && etag) resolve(etag);
      else reject(new ApiError(xhr.status, "UPLOAD_FAILED", "The upload was interrupted.", "Try again."));
    };
    xhr.onerror = () => reject(new ApiError(0, "UPLOAD_FAILED", "The upload was interrupted.", "Check your connection and try again."));
    xhr.send(body);
  });
}

/**
 * Presigned multipart upload: browser -> storage, never through our API.
 * Resolves with the asset id once the API has confirmed the file is complete.
 */
export async function uploadFile(
  file: File,
  kind: UploadKind,
  onProgress: (fraction: number) => void,
): Promise<string> {
  const created = await createUpload(file, kind);
  const ranges = planParts(file.size, created.part_size);
  const urls = new Map(created.parts.map((p) => [p.part_number, p.url]));
  const done: { part_number: number; etag: string }[] = [];
  let finishedBytes = 0;

  for (const range of ranges) {
    const url = urls.get(range.partNumber);
    if (url === undefined) throw new ApiError(0, "UPLOAD_FAILED", "The upload couldn't be prepared.", "Try again.");
    const etag = await putPart(url, file.slice(range.start, range.end), (sent) =>
      onProgress(Math.min((finishedBytes + sent) / file.size, 1)),
    );
    finishedBytes += range.end - range.start;
    done.push({ part_number: range.partNumber, etag });
  }

  await completeUpload(created.asset_id, created.upload_id, done);
  onProgress(1);
  return created.asset_id;
}
