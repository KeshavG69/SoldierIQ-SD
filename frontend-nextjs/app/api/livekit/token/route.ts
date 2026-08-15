import { NextRequest, NextResponse } from "next/server";
import { AccessToken, type VideoGrant } from "livekit-server-sdk";

/**
 * Mint a LiveKit access token for the voice agent.
 *
 * Auth model: the browser sends its Keycloak JWT as `Authorization: Bearer <token>`.
 * We forward it to the KM backend's `/api/auth/me` to resolve the identity — that
 * endpoint already validates the token against Keycloak. If valid, we mint a
 * short-lived LK token with the selected documents embedded as participant metadata
 * so the voice agent can scope retrieval.
 */

export const revalidate = 0;

const API_KEY = process.env.LIVEKIT_API_KEY;
const API_SECRET = process.env.LIVEKIT_API_SECRET;
const LIVEKIT_URL = process.env.LIVEKIT_URL;
const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface StartRequestBody {
  document_ids?: string[];
  file_names?: string[];
}

interface MeResponse {
  id: string;
  organization_id: string;
  email?: string;
  firstName?: string;
  lastName?: string;
}

export async function POST(req: NextRequest) {
  try {
    if (!LIVEKIT_URL || !API_KEY || !API_SECRET) {
      return NextResponse.json(
        { error: "LiveKit server env vars (LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET) are not configured" },
        { status: 500 }
      );
    }

    const authHeader = req.headers.get("authorization");
    if (!authHeader) {
      return NextResponse.json({ error: "Missing Authorization header" }, { status: 401 });
    }

    // Validate the Keycloak JWT via the backend's /auth/me endpoint.
    const meRes = await fetch(`${BACKEND_URL}/api/auth/me`, {
      headers: { Authorization: authHeader },
      cache: "no-store",
    });
    if (!meRes.ok) {
      const body = await meRes.text().catch(() => "");
      console.error(`[/api/livekit/token] /api/auth/me returned ${meRes.status}: ${body}`);
      return NextResponse.json(
        { error: `Backend rejected token (${meRes.status})`, upstream: body || undefined },
        { status: meRes.status === 401 ? 401 : 502 }
      );
    }
    const me = (await meRes.json()) as MeResponse;
    if (!me.id || !me.organization_id) {
      return NextResponse.json({ error: "Backend returned user without id / organization_id" }, { status: 500 });
    }

    const body = (await req.json().catch(() => ({}))) as StartRequestBody;
    const documentIds = Array.isArray(body.document_ids) ? body.document_ids : [];
    const fileNames = Array.isArray(body.file_names) ? body.file_names : [];

    const metadata = JSON.stringify({
      user_id: me.id,
      organization_id: me.organization_id,
      document_ids: documentIds,
      file_names: fileNames,
    });

    const roomName = `voice_${me.id}_${Date.now()}`;
    const participantIdentity = `${me.id}_${Math.floor(Math.random() * 10_000)}`;
    const participantName = [me.firstName, me.lastName].filter(Boolean).join(" ") || me.email || me.id;

    const at = new AccessToken(API_KEY, API_SECRET, {
      identity: participantIdentity,
      name: participantName,
      metadata,
      ttl: "15m",
    });
    const grant: VideoGrant = {
      room: roomName,
      roomJoin: true,
      canPublish: true,
      canPublishData: true,
      canSubscribe: true,
    };
    at.addGrant(grant);

    const participantToken = await at.toJwt();

    return NextResponse.json(
      {
        serverUrl: LIVEKIT_URL,
        roomName,
        participantName,
        participantToken,
      },
      { headers: { "Cache-Control": "no-store" } }
    );
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    console.error("[/api/livekit/token] failed:", err);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
