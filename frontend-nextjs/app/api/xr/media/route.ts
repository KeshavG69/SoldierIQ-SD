import { NextRequest, NextResponse } from "next/server";

/**
 * Same-origin proxy for presigned media (slide images, infographics, videos) used
 * by VR mode. WebGL textures need CORS headers, which the object store doesn't
 * send, so the browser loads them through here instead.
 *
 * Only the object-store host is allowed — this is not a general-purpose proxy. The
 * presigned URL itself carries the authorization. Range requests are forwarded so
 * video can seek.
 */

export const dynamic = "force-dynamic";

const ALLOWED_HOSTS = new Set(
  [process.env.IDRIVEE2_ENDPOINT_URL, process.env.NEXT_PUBLIC_IDRIVEE2_ENDPOINT_URL]
    .filter((u): u is string => !!u)
    .map((u) => {
      try {
        return new URL(u).hostname;
      } catch {
        return "";
      }
    })
    .filter(Boolean),
);

function isAllowed(url: URL) {
  if (url.protocol !== "https:") return false;
  const host = url.hostname;
  if (ALLOWED_HOSTS.has(host)) return true;
  // Virtual-hosted-style bucket URLs: <bucket>.<endpoint host>
  for (const allowed of ALLOWED_HOSTS) if (host.endsWith(`.${allowed}`)) return true;
  return false;
}

const PASSTHROUGH_HEADERS = ["content-type", "content-length", "content-range", "accept-ranges", "etag", "last-modified"];

export async function GET(req: NextRequest) {
  const raw = req.nextUrl.searchParams.get("url");
  if (!raw) return NextResponse.json({ error: "url is required" }, { status: 400 });

  let target: URL;
  try {
    target = new URL(raw);
  } catch {
    return NextResponse.json({ error: "Invalid url" }, { status: 400 });
  }
  if (!isAllowed(target)) return NextResponse.json({ error: "Host not allowed" }, { status: 403 });

  const range = req.headers.get("range");
  const upstream = await fetch(target, {
    headers: range ? { range } : undefined,
    cache: "no-store",
    redirect: "error",
  }).catch(() => null);
  if (!upstream) return NextResponse.json({ error: "Upstream fetch failed" }, { status: 502 });

  const headers = new Headers();
  for (const h of PASSTHROUGH_HEADERS) {
    const v = upstream.headers.get(h);
    if (v) headers.set(h, v);
  }
  headers.set("cache-control", "private, max-age=600");

  return new NextResponse(upstream.body, { status: upstream.status, headers });
}
