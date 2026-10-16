// Thin API client. Every state-changing call carries X-DF-Client (CSRF guard on the backend).

export interface ApiErrorBody {
  code: string;
  vi?: string;
  en?: string;
  detail?: string | null;
  category?: string;
  request_id?: string;
}

export class ApiError extends Error {
  status: number;
  body: ApiErrorBody;
  constructor(status: number, body: ApiErrorBody) {
    super(body.en || body.code);
    this.status = status;
    this.body = body;
  }
}

async function handle<T>(res: Response): Promise<T> {
  const ct = res.headers.get("content-type") || "";
  if (!res.ok) {
    let body: ApiErrorBody = { code: `HTTP_${res.status}` };
    if (ct.includes("application/json")) body = await res.json();
    throw new ApiError(res.status, body);
  }
  if (ct.includes("application/json")) return (await res.json()) as T;
  return undefined as T;
}

export async function get<T = any>(path: string): Promise<T> {
  return handle<T>(await fetch(path, { headers: { Accept: "application/json" } }));
}

async function send<T>(method: string, path: string, body?: unknown): Promise<T> {
  return handle<T>(
    await fetch(path, {
      method,
      headers: { "Content-Type": "application/json", "X-DF-Client": "web" },
      body: body === undefined ? undefined : JSON.stringify(body),
    }),
  );
}

export const post = <T = any>(path: string, body?: unknown) => send<T>("POST", path, body ?? {});
export const put = <T = any>(path: string, body?: unknown) => send<T>("PUT", path, body ?? {});

export async function upload<T = any>(path: string, file: File, fields: Record<string, string> = {}): Promise<T> {
  const fd = new FormData();
  fd.append("file", file);
  Object.entries(fields).forEach(([k, v]) => fd.append(k, v));
  return handle<T>(await fetch(path, { method: "POST", headers: { "X-DF-Client": "web" }, body: fd }));
}

export function qs(params: Record<string, string | number | boolean | undefined | null>): string {
  const p = Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== "");
  return p.length ? "?" + p.map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`).join("&") : "";
}
