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

/** 1.2.8: `timeoutMs` aborts a request that takes longer and fails it with REQUEST_TIMEOUT (never an endless wait);
 *  `signal` lets the caller cancel it (a closed modal). Without options the request is exactly as before. */
export async function get<T = any>(path: string, opts: { timeoutMs?: number; signal?: AbortSignal } = {}): Promise<T> {
  if (!opts.timeoutMs && !opts.signal) return handle<T>(await fetch(path, { headers: { Accept: "application/json" } }));
  const ctl = new AbortController();
  const cancel = () => ctl.abort();
  if (opts.signal?.aborted) ctl.abort();
  opts.signal?.addEventListener("abort", cancel);
  let timedOut = false;
  const timer = opts.timeoutMs ? setTimeout(() => { timedOut = true; ctl.abort(); }, opts.timeoutMs) : undefined;
  try {
    return await handle<T>(await fetch(path, { headers: { Accept: "application/json" }, signal: ctl.signal }));
  } catch (e) {
    if (timedOut) {
      const s = Math.round((opts.timeoutMs ?? 0) / 1000);
      throw new ApiError(0, { code: "REQUEST_TIMEOUT", vi: `Máy chủ chưa trả lời sau ${s} giây — đã dừng chờ. Bấm "Thử lại".`,
        en: `No answer from the server after ${s} s — stopped waiting. Press "Try again".` });
    }
    throw e;
  } finally {
    if (timer) clearTimeout(timer);
    opts.signal?.removeEventListener("abort", cancel);
  }
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
