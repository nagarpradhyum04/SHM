import { CheckCircle2, RefreshCw, XCircle } from "lucide-react";
import { useEffect, useState } from "react";
import { api, API_BASE } from "@/api/client";
import { useAlertRules, useApiMutation, useModels, useSettings, useSystemStatus } from "@/api/hooks";
import type { AlertRule, MqttDiagnosis, MqttStatus, TrainingStatus } from "@/api/types";
import { NotificationsSettings } from "@/components/NotificationsSettings";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Card, ErrorState, Field, KV, Loading, Notice, PageHeader, Segmented, Stat } from "@/components/ui";
import { fmtBytes, fmtDateTime, fmtTime, humanize } from "@/lib/format";
import { PRIORITIES, PRIORITY_LABEL } from "@/lib/priority";
import { useUI } from "@/store/ui";

function Ok({ ok, label }: { ok: boolean; label: string }) {
  return <span className={`inline-flex items-center gap-1 ${ok ? "text-emerald-300" : "text-red-300"}`}>{ok ? <CheckCircle2 className="h-3.5 w-3.5" /> : <XCircle className="h-3.5 w-3.5" />}{label}</span>;
}

/** Small form of labelled number inputs for one settings object (replaces raw JSON editing). */
function NumberSettings({ k, value, title, hint, fields }: {
  k: string; value: Record<string, any>; title: string; hint?: string; fields: { key: string; label: string; help?: string }[];
}) {
  const [v, setV] = useState<Record<string, string>>({});
  const [msg, setMsg] = useState<string | null>(null);
  useEffect(() => setV(Object.fromEntries(fields.map((f) => [f.key, value[f.key] === null || value[f.key] === undefined ? "" : String(value[f.key])]))),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [value]);
  const save = useApiMutation(() => api(`/settings/${k}`, { method: "PUT", json: {
    value: Object.fromEntries(fields.map((f) => [f.key, v[f.key] === "" ? null : Number(v[f.key])])), actor: localStorage.getItem("ss.actor") || null } }),
  ["settings", "system-status"]);
  return (
    <Card title={title} bodyClass="space-y-3 p-3">
      {hint && <p className="text-[11px] text-slate-400">{hint}</p>}
      <div className="grid grid-cols-2 gap-2 md:grid-cols-3">
        {fields.map((f) => (
          <Field key={f.key} label={f.label} hint={f.help}>
            <input className="input" inputMode="decimal" value={v[f.key] ?? ""} onChange={(e) => setV({ ...v, [f.key]: e.target.value })} aria-label={f.label} />
          </Field>
        ))}
      </div>
      <div className="flex items-center gap-2">
        <button className="btn-primary" onClick={() => save.mutate(undefined, { onSuccess: () => setMsg("Saved"), onError: (e) => setMsg((e as Error).message) })}>Save</button>
        {msg && <span className={`text-[11px] ${msg === "Saved" ? "text-emerald-300" : "text-red-300"}`}>{msg}</span>}
      </div>
    </Card>
  );
}

function pct(v: unknown) {
  return typeof v === "number" ? `${(v * 100).toFixed(1)} %` : "—";
}

/** AI crack-detection model: status in plain words, how to get one, upload/install. */
function ModelSection() {
  const status = useSystemStatus();
  const models = useModels();
  const qc = useQueryClient();
  const [onnx, setOnnx] = useState<File | null>(null);
  const [card, setCard] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const reload = useApiMutation(() => api("/models/reload", { method: "POST" }), ["models", "system-status"]);
  const available = status.data?.models.available;
  const install = async () => {
    if (!onnx || !card) return;
    setBusy(true);
    setMsg(null);
    const fd = new FormData();
    fd.append("onnx_file", onnx);
    fd.append("card_file", card);
    try {
      const r = await fetch(`${API_BASE}/models/upload`, { method: "POST", body: fd });
      const b = await r.json().catch(() => null);
      if (!r.ok) throw new Error(typeof b?.detail === "string" ? b.detail : `Install failed (${r.status})`);
      setMsg({ ok: true, text: `Installed ${b.installed} v${b.version}. Webcam frames and uploads are now analysed automatically.` });
      ["models", "system-status"].forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
    } catch (e) {
      setMsg({ ok: false, text: (e as Error).message });
    } finally {
      setBusy(false);
    }
  };
  const installed = (models.data ?? []).filter((m) => m.status === "installed");
  return (
    <div className="grid gap-3 xl:grid-cols-2">
      <Card title="AI crack-detection model" actions={<button className="btn-ghost" onClick={() => reload.mutate(undefined)}><RefreshCw className="h-3.5 w-3.5" />Rescan</button>} bodyClass="space-y-3 p-3">
        <div className={`rounded-md border p-3 text-sm ${available ? "border-emerald-400/30 bg-emerald-400/5" : "border-amber-400/30 bg-amber-400/5"}`}>
          {available ? (
            <><b className="text-emerald-300">Active.</b> Webcam frames and uploaded photos are checked for cracks automatically.</>
          ) : (
            <><b className="text-amber-300">Not installed yet.</b> Connecting the webcam works on its own (live view, hourly photos), but cracks are only
              detected automatically once a trained model is installed here. Nothing is guessed in the meantime.</>
          )}
        </div>
        {installed.map((m) => (
          <div key={m.id} className="rounded border border-white/10 p-2 text-xs">
            <div className="flex justify-between"><span className="mono text-accent-soft">{m.id} v{m.version}</span><span>{m.is_active ? "active" : "installed"}</span></div>
            <div className="mt-1 grid grid-cols-4 gap-2">
              <Stat label="Precision" value={pct(m.metrics?.precision)} /><Stat label="Recall" value={pct(m.metrics?.recall)} />
              <Stat label="F1" value={pct(m.metrics?.f1)} /><Stat label="Missed cracks" value={pct(m.metrics?.false_negative_rate)} />
            </div>
            <div className="mt-1 text-[11px] text-slate-400">Dataset: {m.dataset?.name ?? "not recorded"} {m.dataset?.license ? `(${m.dataset.license})` : ""} ·
              test images: {m.metrics?.n ?? "—"} · threshold {m.threshold}</div>
            {!m.metrics && <div className="text-[11px] text-amber-300">No evaluation recorded — treat its detections as unverified.</div>}
          </div>
        ))}
      </Card>
      <TrainCard />
      <Card title="Or install a trained model" bodyClass="space-y-3 p-3">
        <p className="text-xs text-slate-300">Upload a <code className="mono">model.onnx</code> with its <code className="mono">model_card.json</code> (for example trained on another computer).</p>
        <div className="grid grid-cols-2 gap-2">
          <Field label="model.onnx"><input type="file" accept=".onnx" className="input" onChange={(e) => setOnnx(e.target.files?.[0] ?? null)} aria-label="ONNX model file" /></Field>
          <Field label="model_card.json"><input type="file" accept=".json,application/json" className="input" onChange={(e) => setCard(e.target.files?.[0] ?? null)} aria-label="Model card file" /></Field>
        </div>
        <button className="btn-primary" disabled={!onnx || !card || busy} onClick={install}>{busy ? "Checking & installing…" : "Install model"}</button>
        {msg && <div role={msg.ok ? "status" : "alert"} className={`text-xs ${msg.ok ? "text-emerald-300" : "text-red-300"}`}>{msg.text}</div>}
        <p className="text-[11px] text-slate-500">The model is loaded once as a check before it is activated; a broken file is rejected and nothing changes.</p>
      </Card>
    </div>
  );
}

function PriorityRules({ value }: { value: Record<string, any> }) {
  const [v, setV] = useState(value);
  const [msg, setMsg] = useState<string | null>(null);
  useEffect(() => setV(value), [value]);
  const save = useApiMutation(() => api("/settings/priority_rules", { method: "PUT", json: { value: { ...v, description: undefined }, actor: localStorage.getItem("ss.actor") || null } }), ["settings"]);
  return (
    <Card title="Defect review-priority rules" bodyClass="space-y-3 p-3">
      <Notice tone="warn">{value.description}</Notice>
      <div className="grid gap-2 md:grid-cols-2">
        {Object.entries(v.category_base as Record<string, string>).map(([cat, lvl]) => (
          <label key={cat} className="flex items-center justify-between gap-2 text-xs"><span>{humanize(cat)}</span>
            <select className="input w-36" value={lvl} onChange={(e) => setV({ ...v, category_base: { ...v.category_base, [cat]: e.target.value } })}>
              {[...PRIORITIES].reverse().map((p) => <option key={p} value={p}>{PRIORITY_LABEL[p]}</option>)}
            </select>
          </label>
        ))}
      </div>
      <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
        <Field label="Min AI confidence"><input className="input" value={v.min_ai_confidence} onChange={(e) => setV({ ...v, min_ai_confidence: +e.target.value })} /></Field>
        <Field label="Repeat window (days)"><input className="input" value={v.repeat_window_days} onChange={(e) => setV({ ...v, repeat_window_days: +e.target.value })} /></Field>
        <Field label="Repeat min count"><input className="input" value={v.repeat_min_count} onChange={(e) => setV({ ...v, repeat_min_count: +e.target.value })} /></Field>
        <Field label="Repeat radius (m)"><input className="input" value={v.repeat_radius_m} onChange={(e) => setV({ ...v, repeat_radius_m: +e.target.value })} /></Field>
        <Field label="Corroboration window (h)"><input className="input" value={v.corroboration_window_hours} onChange={(e) => setV({ ...v, corroboration_window_hours: +e.target.value })} /></Field>
        <label className="flex items-center gap-2 pt-5 text-xs"><input type="checkbox" checked={v.raise_on_repeat} onChange={(e) => setV({ ...v, raise_on_repeat: e.target.checked })} />Raise on repeat</label>
        <label className="flex items-center gap-2 pt-5 text-xs"><input type="checkbox" checked={v.raise_on_vibration_corroboration} onChange={(e) => setV({ ...v, raise_on_vibration_corroboration: e.target.checked })} />Raise on vibration corroboration</label>
      </div>
      <Field label="Extent rules (JSON list)" hint='No thresholds are shipped. Example: [{"category":"suspected_crack","field":"width_mm","gte":0.3,"priority":"high"}]'>
        <textarea className="input mono h-16" defaultValue={JSON.stringify(v.extent_rules)} onBlur={(e) => { try { setV({ ...v, extent_rules: JSON.parse(e.target.value || "[]") }); setMsg(null); } catch { setMsg("Extent rules: invalid JSON"); } }} />
      </Field>
      <div className="flex items-center gap-2">
        <button className="btn-primary" onClick={() => save.mutate(undefined, { onSuccess: () => setMsg("Saved — applies to new and recomputed findings"), onError: (e) => setMsg((e as Error).message) })}>Save rules</button>
        {msg && <span className="text-[11px] text-slate-300">{msg}</span>}
      </div>
    </Card>
  );
}

function TrainCard() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["training"], queryFn: () => api<TrainingStatus>("/models/train"),
    refetchInterval: (query) => (["running", "installing"].includes(query.state.data?.state ?? "") ? 2000 : false) });
  const [path, setPath] = useState("");
  const [quick, setQuick] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const t = q.data;
  const busy = t?.state === "running" || t?.state === "installing";
  useEffect(() => {
    if (t?.state === "done") ["models", "system-status"].forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
  }, [t?.state, qc]);
  const start = async () => {
    setErr(null);
    try {
      await api("/models/train", { method: "POST", json: { data_path: path.trim() || null, limit: quick ? 3000 : 20000, epochs: quick ? 5 : 8 } });
      qc.invalidateQueries({ queryKey: ["training"] });
    } catch (e) { setErr((e as Error).message); }
  };
  const m = t?.result?.metrics;
  return (
    <Card title="Train the crack model on this computer" bodyClass="space-y-3 p-3">
      <p className="text-xs text-slate-300">
        Trains a small CNN on the public <i>Concrete Crack Images for Classification</i> dataset (Özgenel, Mendeley Data, CC BY 4.0 — 40,000 photos of
        concrete with and without cracks), tests it on photos it never saw, and installs it. Needs internet once (≈235 MB dataset, plus ≈200 MB for
        PyTorch if it is not installed).
      </p>
      <Field label="Dataset (optional)" hint="Leave empty to download automatically. If the download fails, download it yourself from data.mendeley.com/datasets/5y9wdsg2zt/2 and paste the path of the .zip (or extracted folder) here.">
        <input className="input" placeholder="e.g. C:\Users\you\Downloads\5y9wdsg2zt-2.zip" value={path} onChange={(e) => setPath(e.target.value)} disabled={busy} aria-label="Dataset path" />
      </Field>
      <label className="flex items-center gap-2 text-xs text-slate-300">
        <input type="checkbox" checked={quick} onChange={(e) => setQuick(e.target.checked)} disabled={busy} />
        Quick (6,000 photos, ~10–20 min on a laptop CPU). Untick to use all 40,000 photos (about an hour, slightly better).
      </label>
      <div className="flex items-center gap-2">
        <button className="btn-primary" onClick={start} disabled={busy}>{busy ? "Training…" : t?.state === "done" ? "Train again" : "Train & install"}</button>
        {busy && <button className="btn-ghost" onClick={() => api("/models/train/cancel", { method: "POST" }).then(() => qc.invalidateQueries({ queryKey: ["training"] }))}>Cancel</button>}
      </div>
      {err && <div role="alert" className="text-xs text-red-300">{err}</div>}
      {t && t.state !== "idle" && (
        <div className="space-y-1">
          <div className={`text-xs ${t.state === "failed" ? "text-red-300" : t.state === "done" ? "text-emerald-300" : "text-slate-200"}`}>
            {t.state === "done" ? `Installed ${t.result?.installed} v${t.result?.version}.` : t.state === "failed" ? `Failed: ${t.error}` : t.state === "cancelled" ? "Cancelled." : `Working: ${t.step}`}
          </div>
          {t.state === "done" && m && (
            <div className="text-[11px] text-slate-400">Test results on held-out dataset photos: precision {pct(m.precision)}, recall {pct(m.recall)}, F1 {pct(m.f1)}.
              These are close-up photos; check detections on your own webcam images before relying on it.</div>
          )}
          <pre className="mono max-h-48 overflow-auto rounded border border-white/5 bg-black/30 p-2 text-[10px] text-slate-400">{t.log.filter((l) => !/^\s|^[{}\]]$|^"/.test(l) || l.startsWith("{'")).slice(-30).join("\n")}</pre>
        </div>
      )}
    </Card>
  );
}

function MqttCheck({ m }: { m: MqttStatus }) {
  const qc = useQueryClient();
  const [d, setD] = useState<MqttDiagnosis | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const run = async () => {
    setBusy(true); setErr(null);
    try { setD(await api<MqttDiagnosis>("/mqtt/diagnose?listen_s=5", { method: "POST" })); } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };
  const use = async (host: string | null) => {
    await api("/mqtt/broker", { method: "PUT", json: { host } });
    qc.invalidateQueries({ queryKey: ["mqtt"] });
    setD(null);
  };
  const good = d?.status === "ok";
  return (
    <div className="space-y-2 rounded border border-white/10 p-2">
      <div className="flex flex-wrap items-center gap-2">
        <button className="btn-primary" onClick={run} disabled={busy}>{busy ? "Checking (5 s)…" : "Check connection"}</button>
        <span className="text-[11px] text-slate-400">Finds the brokers on this computer and listens for 5 s to see where your device's messages actually go.</span>
        {m.host_overridden && <button className="btn-ghost" onClick={() => use(null)}>Back to default broker</button>}
      </div>
      {err && <div role="alert" className="text-xs text-red-300">{err}</div>}
      {d && (
        <div className="space-y-2 text-xs">
          <div className={`rounded border p-2 ${good ? "border-emerald-400/30 bg-emerald-400/5 text-emerald-200" : "border-amber-400/30 bg-amber-400/5 text-amber-100"}`}>
            <div className="font-semibold">{d.summary}</div>
            <div className="mt-1 text-slate-300">{d.fix}</div>
            {d.suggest_host && <button className="btn-primary mt-2" onClick={() => use(d.suggest_host)}>Use {d.suggest_host}</button>}
          </div>
          <table className="table-base">
            <thead><tr><th>Address</th><th>Broker</th><th>Messages seen in 5 s</th></tr></thead>
            <tbody>{d.brokers.map((b) => (
              <tr key={b.host}>
                <td className="mono">{b.host}:{b.port}{b.is_backend && <span className="ml-1 text-accent-soft">(backend)</span>}{b.lan && <span className="ml-1 text-slate-500">(network)</span>}</td>
                <td>{!b.listening ? <span className="text-red-300">not listening{b.error ? ` — ${b.error}` : ""}</span>
                  : b.same_broker_as.length ? `same broker as ${b.same_broker_as.join(", ")}` : b.mqtt_ok ? "separate broker" : <span className="text-amber-300">{b.error}</span>}</td>
                <td className="text-[11px]">{b.topics.length ? b.topics.map((t) => <div key={t.topic}><span className="mono">{t.topic}</span> ×{t.count} <span className="text-slate-500">{t.sample?.slice(0, 70)}</span></div>) : <span className="text-slate-500">none</span>}</td>
              </tr>
            ))}</tbody>
          </table>
          {d.status === "localhost_only" && (
            <div className="text-[11px] text-slate-400">Script: in the project folder, open PowerShell <b>as administrator</b> and run
              <code className="mono"> powershell -ExecutionPolicy Bypass -File scripts\start-broker.ps1</code>. It makes the Mosquitto service listen on the network, starts it with Windows and opens port 1883 in the firewall.</div>
          )}
        </div>
      )}
    </div>
  );
}

function MqttCard() {
  const q = useQuery({ queryKey: ["mqtt"], queryFn: () => api<MqttStatus>("/mqtt/status"), refetchInterval: 5000 });
  const m = q.data;
  return (
    <Card title="IoT connection (MQTT)" bodyClass="space-y-2 p-3">
      {!m ? <Loading /> : (
        <>
          <KV k="Bridge" v={<Ok ok={m.state === "connected"} label={m.enabled ? `${m.state} · ${m.broker}` : "disabled (SS_MQTT_ENABLED=false)"} />} />
          {m.last_error && <KV k="Last error" v={<span className="text-amber-300">{m.last_error}</span>} />}
          <KV k="Topics" v={m.topic} mono />
          <KV k="Broker auth" v={m.auth} />
          <KV k="Messages" v={`${m.counts.received} received · ${m.counts.accepted} accepted · ${m.counts.rejected} rejected`} />
          <MqttCheck m={m} />
          <div className="label pt-1">Recent messages</div>
          <div className="max-h-56 overflow-auto rounded border border-white/5">
            {m.recent.length === 0 ? (
              <div className="space-y-1 p-2 text-[11px] text-slate-400">
                <div className="text-slate-300">Nothing received yet. Even rejected messages are listed here, so the backend is not getting them at all — press <b>Check connection</b> above.</div>
                <div>Manual checks: 1. Check the broker sees the ESP32: <code className="mono">mosquitto_sub -h 127.0.0.1 -t "bridge/#" -v</code> — if nothing appears, also try <code className="mono">-h &lt;laptop IP&gt;</code>.</div>
                <div>2. If only the laptop-IP command shows data, two brokers are running (on Windows the "Mosquitto Broker" service listens on 127.0.0.1). Stop that service
                  (<code className="mono">net stop mosquitto</code>, as administrator) or set <code className="mono">SS_MQTT_HOST=&lt;laptop IP&gt;</code> in <code className="mono">backend/.env</code> and restart the backend.</div>
                <div>3. Allow TCP 1883 in the Windows firewall for private networks.</div>
              </div>
            ) : (
              <table className="table-base">
                <tbody>{m.recent.map((r, i) => (
                  <tr key={i}><td className="mono">{fmtTime(r.ts)}</td><td className="mono">{r.topic}</td>
                    <td className={r.outcome === "accepted" ? "text-emerald-300" : "text-red-300"}>{r.outcome}</td><td className="text-[11px] text-slate-400">{r.detail}</td></tr>
                ))}</tbody>
              </table>
            )}
          </div>
        </>
      )}
    </Card>
  );
}

function LimitsCard({ vibration, environment }: { vibration: Record<string, any>; environment: Record<string, any> }) {
  const fields: { key: string; group: "vibration" | "environment"; label: string; hint: string }[] = [
    { key: "abs_rms_dyn_limit_g", group: "vibration", label: "Vibration RMS limit (g)", hint: "60 s window RMS of dynamic acceleration" },
    { key: "abs_peak_dyn_limit_g", group: "vibration", label: "Vibration peak limit (g)", hint: "largest dynamic deviation in a window" },
    { key: "tilt_change_limit_deg", group: "vibration", label: "Tilt change limit (°)", hint: "vs the sensor's reference tilt (set at first data)" },
    { key: "temp_max_c", group: "environment", label: "Max temperature (°C)", hint: "" },
    { key: "temp_min_c", group: "environment", label: "Min temperature (°C)", hint: "" },
    { key: "humidity_max_pct", group: "environment", label: "Max humidity (%)", hint: "" },
    { key: "condensation_margin_c", group: "environment", label: "Condensation margin (°C)", hint: "alert when air temp − dew point is below this" },
    { key: "consecutive_samples", group: "environment", label: "Consecutive samples", hint: "readings that must all violate before alerting" },
  ];
  const [v, setV] = useState<Record<string, string>>({});
  useEffect(() => setV(Object.fromEntries(fields.map((f) => [f.key, String((f.group === "vibration" ? vibration : environment)[f.key] ?? "")])))
    // eslint-disable-next-line react-hooks/exhaustive-deps
    , [vibration, environment]);
  const [msg, setMsg] = useState<string | null>(null);
  const save = useApiMutation(async () => {
    const pick = (g: string) => Object.fromEntries(fields.filter((f) => f.group === g).map((f) => [f.key, v[f.key] === "" ? null : Number(v[f.key])]));
    const actor = localStorage.getItem("ss.actor") || null;
    await api("/settings/vibration", { method: "PUT", json: { value: pick("vibration"), actor } });
    await api("/settings/environment", { method: "PUT", json: { value: pick("environment"), actor } });
  }, ["settings"]);
  return (
    <Card title="Alert limits (set by the responsible engineer)" bodyClass="space-y-3 p-3">
      <Notice tone="warn">No limit values are shipped. Leave a field empty to disable it. Vibration limits trigger the “Vibration above configured limit” alert
        from the MPU6050 windows; the baseline-relative anomaly rule keeps working independently. Temperature/humidity limits describe exposure conditions —
        they cannot detect cracks.</Notice>
      <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
        {fields.map((f) => (
          <Field key={f.key} label={f.label} hint={f.hint || undefined}>
            <input className="input" inputMode="decimal" value={v[f.key] ?? ""} onChange={(e) => setV({ ...v, [f.key]: e.target.value })} aria-label={f.label} />
          </Field>
        ))}
      </div>
      <div className="flex items-center gap-2">
        <button className="btn-primary" onClick={() => save.mutate(undefined, { onSuccess: () => setMsg("Saved"), onError: (e) => setMsg((e as Error).message) })}>Save limits</button>
        {msg && <span className="text-[11px] text-slate-300">{msg}</span>}
      </div>
    </Card>
  );
}

function RuleRow({ r }: { r: AlertRule }) {
  const patch = useApiMutation((body: Partial<AlertRule>) => api(`/alert-rules/${r.id}`, { method: "PATCH", json: { ...body, actor: localStorage.getItem("ss.actor") || null } }), ["alert-rules"]);
  const [cool, setCool] = useState(String(r.cooldown_s));
  return (
    <tr>
      <td><div className="text-slate-100">{r.name}</div><div className="max-w-md text-[10px] text-slate-500">{r.description}</div></td>
      <td><input type="checkbox" checked={r.enabled} onChange={(e) => patch.mutate({ enabled: e.target.checked })} aria-label={`Enable ${r.name}`} /></td>
      <td><select className="input w-28" value={r.priority} onChange={(e) => patch.mutate({ priority: e.target.value as AlertRule["priority"] })}>{PRIORITIES.filter((p) => p !== "unassessed").map((p) => <option key={p} value={p}>{PRIORITY_LABEL[p]}</option>)}</select></td>
      <td><input className="input w-24" value={cool} onChange={(e) => setCool(e.target.value)} onBlur={() => +cool !== r.cooldown_s && patch.mutate({ cooldown_s: +cool })} aria-label={`Cooldown ${r.name}`} /></td>
      <td className="mono">v{r.version}</td>
    </tr>
  );
}

type Tab = "overview" | "alerts" | "notifications" | "model" | "data" | "advanced";
const TABS: { k: Tab; label: string }[] = [
  { k: "overview", label: "Overview" }, { k: "alerts", label: "Alert limits & rules" }, { k: "notifications", label: "Messages" }, { k: "model", label: "AI model" },
  { k: "data", label: "Data & devices" }, { k: "advanced", label: "Advanced" },
];

export default function SettingsPage() {
  const status = useSystemStatus();
  const settings = useSettings();
  const rules = useAlertRules();
  const reducedMotion = useUI((s) => s.reducedMotion);
  const setReducedMotion = useUI((s) => s.setReducedMotion);
  const setMode = useApiMutation((mode: string) => api("/settings/data_source", { method: "PUT", json: { value: { mode } } }), ["system-status", "settings"]);
  const s = status.data;
  const [tab, setTab] = useState<Tab>(() => (location.hash === "#rules" ? "alerts" : (location.hash.slice(1) as Tab)) || "overview");
  const go = (t: Tab) => { setTab(t); history.replaceState(null, "", `#${t}`); };
  const sv = settings.data;
  return (
    <div className="space-y-3 pb-6">
      <PageHeader title="Settings & System Health" subtitle="Connection status, alert limits, the AI model and data options." />
      <div className="mx-5 flex flex-wrap gap-1 border-b border-white/10" role="tablist">
        {TABS.map((t) => (
          <button key={t.k} role="tab" aria-selected={tab === t.k} onClick={() => go(t.k)}
            className={`-mb-px border-b-2 px-3 py-2 text-xs font-medium ${tab === t.k ? "border-accent text-accent-soft" : "border-transparent text-slate-400 hover:text-white"}`}>{t.label}</button>
        ))}
      </div>
      <div className="px-5">
        {tab === "overview" && (
          <div className="grid gap-3 xl:grid-cols-2">
            <Card title="System status" bodyClass="p-3">
              {status.isLoading ? <Loading /> : status.isError ? <ErrorState error={status.error} onRetry={() => status.refetch()} /> : s && (
                <div>
                  <KV k="Backend" v={<Ok ok label="running" />} />
                  <KV k="Database" v={<Ok ok={s.database.ok} label={s.database.ok ? "OK" : "error"} />} />
                  <KV k="Storage" v={<Ok ok={s.storage.ok && !!s.storage.writable} label={s.storage.ok ? `${fmtBytes(s.storage.disk_free_bytes)} free` : s.storage.error ?? "error"} />} />
                  <KV k="IoT (MQTT)" v={<Ok ok={s.mqtt.state === "connected"} label={s.mqtt.enabled ? s.mqtt.state : "disabled"} />} />
                  <KV k="AI model" v={<Ok ok={s.models.available} label={s.models.available ? "installed" : "not installed"} />} />
                  <KV k="Real sensor data" v={s.real_data_configured ? `last received ${fmtDateTime(s.last_real_reading_received_at)}` : "none received yet"} />
                  <KV k="User login" v={<span className="text-amber-300">not implemented (single-user local build)</span>} />
                  <div className="mt-3 flex flex-wrap gap-2 text-xs">
                    <a className="btn-ghost" href="/api/v1" target="_blank" rel="noreferrer">API index</a>
                    <a className="btn-ghost" href="/docs" target="_blank" rel="noreferrer">API documentation</a>
                  </div>
                </div>
              )}
            </Card>
            <MqttCard />
          </div>
        )}
        {tab === "alerts" && (
          <div className="space-y-3">
            {sv && <LimitsCard vibration={sv.vibration} environment={sv.environment} />}
            <Card title="Alert rules" bodyClass="overflow-auto">
              {rules.isLoading ? <Loading /> : (
                <table className="table-base">
                  <thead><tr><th>Rule</th><th>On</th><th>Priority</th><th>Repeat wait (s)</th><th>Version</th></tr></thead>
                  <tbody>{(rules.data ?? []).map((r) => <RuleRow key={r.id} r={r} />)}</tbody>
                </table>
              )}
            </Card>
          </div>
        )}
        {tab === "notifications" && <NotificationsSettings />}
        {tab === "model" && <ModelSection />}
        {tab === "data" && (
          <div className="grid gap-3 xl:grid-cols-2">
            <Card title="What the dashboards show" bodyClass="space-y-3 p-3">
              <Segmented value={s?.data_source.mode ?? "all"} onChange={(m) => setMode.mutate(m)} options={[{ value: "all", label: "All (labelled)" }, { value: "real", label: "Real only" }, { value: "uploaded", label: "Uploaded" }, { value: "simulated", label: "Simulated" }]} />
              <p className="text-[11px] text-slate-400">Real, uploaded and simulated data are stored separately and always labelled; they are never mixed in one chart line.</p>
              <label className="flex items-center justify-between text-xs">Reduced motion (no pulsing markers or camera animation)
                <input type="checkbox" checked={reducedMotion} onChange={(e) => setReducedMotion(e.target.checked)} aria-label="Reduced motion" /></label>
            </Card>
            {sv && <NumberSettings k="device_status" title="When is a device stale / offline?" value={sv.device_status} hint="Time since the last real reading."
              fields={[{ key: "stale_after_s", label: "Stale after (s)" }, { key: "offline_after_s", label: "Offline after (s)" }]} />}
            {sv && <NumberSettings k="retention" title="Data retention" value={sv.retention} hint="Raw readings older than this are deleted after processing; window features are kept."
              fields={[{ key: "raw_readings_days", label: "Raw readings (days)" }, { key: "features_days", label: "Features (days)" }]} />}
          </div>
        )}
        {tab === "advanced" && (
          <div className="space-y-3">
            {sv && <NumberSettings k="vibration" title="Vibration analysis parameters" value={sv.vibration} hint="Recorded with every evaluated window. Change only if you know why."
              fields={[{ key: "window_s", label: "Window length (s)" }, { key: "anomaly_k_sigma", label: "Anomaly k·σ (RMS)" }, { key: "peak_k_sigma", label: "Anomaly k·σ (peak)" },
                { key: "min_baseline_windows", label: "Min windows for a baseline" }, { key: "min_window_completeness", label: "Min window completeness (0–1)" }]} />}
            {sv?.priority_rules && <PriorityRules value={sv.priority_rules} />}
          </div>
        )}
      </div>
    </div>
  );
}
