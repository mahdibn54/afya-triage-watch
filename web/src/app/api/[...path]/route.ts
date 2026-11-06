// /api/* → the FastAPI app (docs/api.md: the proxy strips the /api prefix).
// The target is read at request time, so one image works for any API_INTERNAL_URL.
import type { NextRequest } from "next/server";

type Ctx = { params: Promise<{ path: string[] }> };

const HOP_BY_HOP = new Set(["connection", "keep-alive", "transfer-encoding", "upgrade", "host", "content-length"]);

async function handle(req: NextRequest, ctx: Ctx): Promise<Response> {
  const { path } = await ctx.params;
  return proxy(req, path);
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
