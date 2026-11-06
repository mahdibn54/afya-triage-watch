// /api/* → the FastAPI app (docs/api.md: the proxy strips the /api prefix).
// FAKE_API=1 serves the in-memory fake instead (built from the contract's example JSON) until E7-10.
// The target is read at request time, so one image works for any API_INTERNAL_URL.
import { cookies } from "next/headers";
import type { NextRequest } from "next/server";

import { FAKE_COOKIE, fakeHandle } from "@/server/fake-api";

type Ctx = { params: Promise<{ path: string[] }> };

const HOP_BY_HOP = new Set(["connection", "keep-alive", "transfer-encoding", "upgrade", "host", "content-length"]);

async function handle(req: NextRequest, ctx: Ctx): Promise<Response> {
  const { path } = await ctx.params;
  if (process.env.FAKE_API === "1") return fake(req, path);
  return proxy(req, path);
}

async function fake(req: NextRequest, path: string[]): Promise<Response> {
  const jar = await cookies();
  let body: unknown = null;
  if (req.method !== "GET" && req.method !== "HEAD") {
    const text = await req.text();
    if (text) {
      try {
        body = JSON.parse(text);
      } catch {
        return Response.json({ error: { code: "invalid", message: "body is not JSON" } }, { status: 422 });
      }
    }
  }
  const res = fakeHandle({
    method: req.method,
    path,
    search: req.nextUrl.searchParams,
    body,
    userId: jar.get(FAKE_COOKIE)?.value ?? null,
  });
  if (res.setUser !== undefined) {
    if (res.setUser) jar.set(FAKE_COOKIE, res.setUser, { httpOnly: true, sameSite: "strict", path: "/" });
    else jar.delete(FAKE_COOKIE);
  }
  return Response.json(res.body, { status: res.status, headers: { "x-afya-fake": "1" } });
}

async function proxy(req: NextRequest, path: string[]): Promise<Response> {
  const base = process.env.API_INTERNAL_URL;
  if (!base) {
    return Response.json({ error: { code: "unavailable", message: "API_INTERNAL_URL is not set" } }, { status: 503 });
  }
  const url = new URL(path.map(encodeURIComponent).join("/"), base.endsWith("/") ? base : base + "/");
  url.search = req.nextUrl.search;
  const headers = new Headers();
  req.headers.forEach((v, k) => {
    if (!HOP_BY_HOP.has(k)) headers.set(k, v);
  });
  try {
    const upstream = await fetch(url, {
      method: req.method,
      headers,
      body: req.method === "GET" || req.method === "HEAD" ? undefined : await req.arrayBuffer(),
      redirect: "manual",
      cache: "no-store",
    });
    const out = new Headers();
    upstream.headers.forEach((v, k) => {
      if (!HOP_BY_HOP.has(k) && k !== "content-encoding") out.append(k, v);
    });
    return new Response(upstream.body, { status: upstream.status, headers: out });
  } catch {
    return Response.json({ error: { code: "unavailable", message: "the API is not reachable" } }, { status: 503 });
  }
}

export const GET = handle;
export const POST = handle;
