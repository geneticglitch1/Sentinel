import { NextResponse } from "next/server";
import { agentGet } from "../_agent";

export const dynamic = "force-dynamic";

// Recent deploys = audit rows for the deploy_container tool.
export async function GET() {
  try {
    const rows = await agentGet("/api/audit?limit=100");
    const deploys = (rows || []).filter((r) => r.tool === "deploy_container");
    return NextResponse.json(deploys);
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 502 });
  }
}
