// Single place that knows where the API lives. By default requests are
// same-origin and Next rewrites /api/* to the backend (next.config.mjs).
export const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "";

export type ApiErrorBody = {
  code: string;
  message: string;
  suggestion?: string;
  field?: string | null;
  recoverable?: boolean;
  errors?: string[];
};

export class ApiError extends Error {
  status: number;
  body: ApiErrorBody;
  constructor(status: number, body: ApiErrorBody) {
    super(body.message);
    this.status = status;
    this.body = body;
  }
}

async function handle<T>(res: Response): Promise<T> {
  if (res.ok) return (await res.json()) as T;
  let body: ApiErrorBody = { code: "http_" + res.status, message: `Request failed (${res.status}).` };
  try {
    const j = await res.json();
    if (j?.error) body = j.error;
  } catch {
    /* non-JSON error body */
  }
  throw new ApiError(res.status, body);
}

export async function apiGet<T>(path: string, params?: Record<string, string | number | undefined | null>): Promise<T> {
  const q = params
    ? "?" +
      Object.entries(params)
        .filter(([, v]) => v !== undefined && v !== null && v !== "")
        .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
        .join("&")
    : "";
  return handle<T>(await fetch(`${API_BASE}${path}${q === "?" ? "" : q}`, { cache: "no-store" }));
}

export async function apiSend<T>(method: "POST" | "PUT" | "PATCH" | "DELETE", path: string, body?: unknown): Promise<T> {
  return handle<T>(
    await fetch(`${API_BASE}${path}`, {
      method,
      headers: body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    }),
  );
}

export async function apiUpload<T>(path: string, files: File[]): Promise<T> {
  const fd = new FormData();
  files.forEach((f) => fd.append("files", f, f.name));
  return handle<T>(await fetch(`${API_BASE}${path}`, { method: "POST", body: fd }));
}

export function downloadUrl(path: string): string {
  return `${API_BASE}${path}`;
}

export function errorText(e: unknown): string {
  if (e instanceof ApiError) {
    const extra = e.body.errors?.length ? " " + e.body.errors.join(" · ") : "";
    return `${e.body.message}${e.body.suggestion ? " " + e.body.suggestion : ""}${extra}`;
  }
  if (e instanceof TypeError) return "Cannot reach the SENTINEL service. Check that the backend is running.";
  return e instanceof Error ? e.message : String(e);
}
