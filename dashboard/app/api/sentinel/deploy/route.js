import { NextResponse } from "next/server";
import { agentPost } from "../_agent";

export const dynamic = "force-dynamic";

// POST { sentence, confirm } -> runs the agent (plan-only unless confirm:true).
export async function POST(request) {
  try {
    const body = await request.json();
    const out = await agentPost("/api/deploy", {
      sentence: body.sentence || "",
      confirm: Boolean(body.confirm),
    });
    return NextResponse.json(out);
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 502 });
  }
}
