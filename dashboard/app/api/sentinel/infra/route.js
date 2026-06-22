import { NextResponse } from "next/server";
import { agentGet } from "../_agent";

export const dynamic = "force-dynamic";

export async function GET() {
  try {
    return NextResponse.json(await agentGet("/api/infra"));
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 502 });
  }
}
