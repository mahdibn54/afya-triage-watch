// Thin client for /api/* (docs/api.md). Errors always carry the contract's { error: { code, message } }.
import type { ApiErrorBody } from "@/api/contract";

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public problems?: unknown[],
  ) {
    super(message);
  }
}

export async function api<T>(path: string, init?: { method?: "GET" | "POST"; body?: unknown }): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`/api${path}`, {
      method: init?.method ?? "GET",
      headers: init?.body !== undefined ? { "content-type": "application/json" } : undefined,
      body: init?.body !== undefined ? JSON.stringify(init.body) : undefined,
      credentials: "same-origin",
      cache: "no-store",
    });
  } catch {
    throw new ApiError(0, "unavailable", "Can't reach the server. Check the connection.");
  }
  const text = await res.text();
  let data: unknown = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = null;
  }
  if (!res.ok) {
    const e = (data as ApiErrorBody | null)?.error;
    throw new ApiError(res.status, e?.code ?? "error", e?.message ?? `Request failed (${res.status})`, e?.problems ?? undefined);
  }
  return data as T;
}

export function newIdempotencyKey(): string {
  return crypto.randomUUID();
}
