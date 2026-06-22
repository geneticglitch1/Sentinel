// Base URL of the sentinel-agent FastAPI service (see docker-compose.yml).
// On .217 with the compose stack this resolves to the agent container.
export const AGENT_URL =
  process.env.SENTINEL_AGENT_URL || "http://sentinel-agent:8799";

export async function agentGet(path) {
  const r = await fetch(`${AGENT_URL}${path}`, { cache: "no-store" });
  if (!r.ok) throw new Error(`agent ${path} -> ${r.status}`);
  return r.json();
}

export async function agentPost(path, body) {
  const r = await fetch(`${AGENT_URL}${path}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
    cache: "no-store",
  });
  if (!r.ok) throw new Error(`agent ${path} -> ${r.status}`);
  return r.json();
}
