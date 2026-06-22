"use client";

// Drop-in Sentinel panels for the secdash dashboard: one-sentence-deploy console,
// live infra (Proxmox VMs + Docker containers), and the audit log. Styled to match
// the neon/terminal aesthetic; tweak the CSS vars to fit your theme.
import { useCallback, useEffect, useState } from "react";

const POLL_MS = 8000;

export default function SentinelPanels() {
  const [infra, setInfra] = useState({ vms: [], containers: [] });
  const [audit, setAudit] = useState([]);
  const [sentence, setSentence] = useState("");
  const [busy, setBusy] = useState(false);
  const [out, setOut] = useState(null);

  const refresh = useCallback(async () => {
    try {
      const [i, a] = await Promise.all([
        fetch("/api/sentinel/infra").then((r) => r.json()),
        fetch("/api/sentinel/audit?limit=40").then((r) => r.json()),
      ]);
      if (!i.error) setInfra(i);
      if (Array.isArray(a)) setAudit(a);
    } catch (_) {}
  }, []);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, POLL_MS);
    return () => clearInterval(t);
  }, [refresh]);

  const run = async (confirm) => {
    if (!sentence.trim()) return;
    setBusy(true);
    setOut(null);
    try {
      const r = await fetch("/api/sentinel/deploy", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ sentence, confirm }),
      }).then((x) => x.json());
      setOut(r);
      refresh();
    } catch (e) {
      setOut({ error: String(e) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="sentinel">
      <section className="s-card s-deploy">
        <h3>root@sentinel:~# deploy</h3>
        <textarea
          rows={2}
          value={sentence}
          placeholder='e.g. "run postgres:16 on the docker host, 2GB RAM, expose 5432, volume pgdata"'
          onChange={(e) => setSentence(e.target.value)}
        />
        <div className="s-row">
          <button disabled={busy} onClick={() => run(false)}>
            {busy ? "…" : "PLAN (dry-run)"}
          </button>
          <button className="s-apply" disabled={busy} onClick={() => run(true)}>
            APPLY ⚠
          </button>
        </div>
        {out && (
          <pre className="s-out">
            {out.error
              ? `error: ${out.error}`
              : (out.tool_calls || [])
                  .map((t) => `→ ${t.name} ${JSON.stringify(t.input)}`)
                  .join("\n") + "\n\n" + (out.text || "")}
          </pre>
        )}
      </section>

      <section className="s-card">
        <h3>// infra</h3>
        <div className="s-grid">
          <div>
            <h4>proxmox</h4>
            {(infra.vms || []).map((v) => (
              <div key={v.vmid} className="s-line">
                <span className={`dot ${v.status === "running" ? "up" : "down"}`} />
                {v.vmid} · {v.name} <em>{v.status}</em>
              </div>
            ))}
          </div>
          <div>
            <h4>docker</h4>
            {(infra.containers || []).map((c) => (
              <div key={c.name} className="s-line">
                <span className={`dot ${c.state === "running" ? "up" : "down"}`} />
                {c.name} <em>{c.state}</em>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="s-card">
        <h3>// audit log</h3>
        <div className="s-audit">
          {audit.map((r) => (
            <div key={r.id} className={`s-line ${r.destructive ? "destructive" : ""}`}>
              <span className={`tag ${r.applied ? "applied" : "plan"}`}>
                {r.applied ? "APPLIED" : "PLAN"}
              </span>
              <b>{r.tool}</b> {r.summary}
              <span className="ts">{r.ts}</span>
            </div>
          ))}
        </div>
      </section>

      <style jsx>{`
        .sentinel {
          --neon: #39ff14;
          --cyan: #00e5ff;
          --bg: #0a0e0a;
          --card: #0e140e;
          color: var(--neon);
          font-family: "JetBrains Mono", ui-monospace, monospace;
          display: grid;
          gap: 16px;
        }
        .s-card {
          background: var(--card);
          border: 1px solid #163216;
          border-radius: 8px;
          padding: 14px 16px;
          box-shadow: 0 0 18px rgba(57, 255, 20, 0.07);
        }
        h3 {
          margin: 0 0 10px;
          color: var(--cyan);
          letter-spacing: 0.05em;
        }
        h4 {
          margin: 4px 0;
          color: #8affc1;
        }
        textarea {
          width: 100%;
          background: #060906;
          color: var(--neon);
          border: 1px solid #1c3a1c;
          border-radius: 6px;
          padding: 8px;
          font-family: inherit;
        }
        .s-row {
          display: flex;
          gap: 10px;
          margin-top: 8px;
        }
        button {
          background: transparent;
          color: var(--neon);
          border: 1px solid var(--neon);
          border-radius: 6px;
          padding: 6px 14px;
          cursor: pointer;
          font-family: inherit;
        }
        button:hover {
          background: rgba(57, 255, 20, 0.12);
        }
        .s-apply {
          color: #ff5b5b;
          border-color: #ff5b5b;
        }
        .s-out {
          margin-top: 10px;
          background: #060906;
          padding: 10px;
          border-radius: 6px;
          white-space: pre-wrap;
          color: #cfeccf;
          max-height: 260px;
          overflow: auto;
        }
        .s-grid {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 16px;
        }
        .s-line {
          padding: 3px 0;
          font-size: 13px;
          display: flex;
          align-items: center;
          gap: 8px;
        }
        .dot {
          width: 9px;
          height: 9px;
          border-radius: 50%;
          display: inline-block;
        }
        .dot.up {
          background: var(--neon);
          box-shadow: 0 0 8px var(--neon);
        }
        .dot.down {
          background: #5a5a5a;
        }
        em {
          color: #7fae7f;
          font-style: normal;
        }
        .s-audit {
          max-height: 320px;
          overflow: auto;
        }
        .tag {
          font-size: 11px;
          padding: 1px 6px;
          border-radius: 4px;
          border: 1px solid currentColor;
        }
        .tag.applied {
          color: #ff9a3c;
        }
        .tag.plan {
          color: var(--cyan);
        }
        .s-line.destructive b {
          color: #ff5b5b;
        }
        .ts {
          margin-left: auto;
          color: #4f6f4f;
          font-size: 11px;
        }
      `}</style>
    </div>
  );
}
