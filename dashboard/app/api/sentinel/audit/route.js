import { NextResponse } from "next/server";
import { agentGet } from "../_agent";

export const dynamic = "force-dynamic";

export async function GET(request) {
  const limit = new URL(request.url).searchParams.get("limit") || "50";
  try {
    return NextResponse.json(await agentGet(`/api/audit?limit=${limit}`));
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 502 });
  }
}
