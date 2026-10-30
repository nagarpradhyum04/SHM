import { CheckCircle2, RefreshCw, XCircle } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "@/api/client";
import { useAlertRules, useApiMutation, useModels, useSettings, useSystemStatus } from "@/api/hooks";
import type { AlertRule, MqttStatus } from "@/api/types";
import { useQuery } from "@tanstack/react-query";
import { Card, ErrorState, Field, KV, Loading, Notice, PageHeader, Segmented } from "@/components/ui";
import { fmtBytes, fmtDateTime, fmtTime, humanize } from "@/lib/format";
import { PRIORITIES, PRIORITY_LABEL } from "@/lib/priority";
import { useUI } from "@/store/ui";

function Ok({ ok, label }: { ok: boolean; label: string }) {
  return <span className={`inline-flex items-center gap-1 ${ok ? "text-emerald-300" : "text-red-300"}`}>{ok ? <CheckCircle2 className="h-3.5 w-3.5" /> : <XCircle className="h-3.5 w-3.5" />}{label}</span>;
}

function JsonSetting({ k, value, title, hint }: { k: string; value: Record<string, any>; title: string; hint?: string }) {
  const [text, setText] = useState(JSON.stringify(value, null, 2));
  const [msg, setMsg] = useState<string | null>(null);
  useEffect(() => setText(JSON.stringify(value, null, 2)), [value]);
  const save = useApiMutation((v: unknown) => api(`/settings/${k}`, { method: "PUT", json: { value: v, actor: localStorage.getItem("ss.actor") || null } }), ["settings", "system-status"]);
  return (
    <Card title={title} bodyClass="space-y-2 p-3">
      {hint && <p className="text-[11px] text-slate-400">{hint}</p>}
      <textarea className="input mono h-48" value={text} onChange={(e) => setText(e.target.value)} aria-label={`${title} JSON`} spellCheck={false} />
      <div className="flex items-center gap-2">
        <button className="btn-primary" onClick={() => {
          let v: unknown;
          try { v = JSON.parse(text); } catch { return setMsg("Invalid JSON"); }
          save.mutate(v, { onSuccess: () => setMsg("Saved"), onError: (e) => setMsg((e as Error).message) });
        }}>Save</button>
        {msg && <span className={`text-[11px] ${msg === "Saved" ? "text-emerald-300" : "text-red-300"}`}>{msg}</span>}
      </div>
    </Card>
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
          <div className="label pt-1">Recent messages</div>
          <div className="max-h-56 overflow-auto rounded border border-white/5">
            {m.recent.length === 0 ? <div className="p-2 text-[11px] text-slate-500">Nothing received yet. Check that the ESP32 publishes to this broker (laptop IP, port 1883) and that the firewall allows it.</div> : (
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

export default function SettingsPage() {
  const status = useSystemStatus();
  const settings = useSettings();
  const rules = useAlertRules();
  const models = useModels();
  const reducedMotion = useUI((s) => s.reducedMotion);
  const setReducedMotion = useUI((s) => s.setReducedMotion);
  const reload = useApiMutation(() => api("/models/reload", { method: "POST" }), ["models", "system-status"]);
  const setMode = useApiMutation((mode: string) => api("/settings/data_source", { method: "PUT", json: { value: { mode } } }), ["system-status", "settings"]);
  const s = status.data;
  useEffect(() => { if (location.hash === "#rules") document.getElementById("rules")?.scrollIntoView(); }, [rules.data]);
  return (
    <div className="space-y-3 pb-6">
      <PageHeader title="Settings & System Health" subtitle="Data sources, rules, model configuration, device ingestion and backend health." />
      <div className="grid gap-3 px-5 xl:grid-cols-2">
        <Card title="System health" bodyClass="p-3">
          {status.isLoading ? <Loading /> : status.isError ? <ErrorState error={status.error} onRetry={() => status.refetch()} /> : s && (
            <div>
              <KV k="Backend" v={<Ok ok label={`${s.app} · API ${s.api_version} · ${s.environment}`} />} />
              <KV k="Database" v={<Ok ok={s.database.ok} label={s.database.dialect} />} />
              <KV k="Storage" v={<Ok ok={s.storage.ok && !!s.storage.writable} label={s.storage.ok ? `${s.storage.files} files · ${fmtBytes(s.storage.bytes)} · ${fmtBytes(s.storage.disk_free_bytes)} free` : s.storage.error ?? "error"} />} />
              <KV k="Inference models" v={<Ok ok={s.models.available} label={s.models.available ? s.models.loaded.map((m) => `${m.id} v${m.version}`).join(", ") : "No model installed (inference unavailable)"} />} />
              {Object.keys(s.models.errors).length > 0 && <KV k="Model errors" v={JSON.stringify(s.models.errors)} mono />}
 <KV k="MQTT bridge" v={<Ok ok={s.mqtt.state === "connected"} label={s.mqtt.enabled ? `${s.mqtt.state} (${s.mqtt.broker})` : "disabled"} />} />
              <KV k="Background jobs" v={<Ok ok={s.background_enabled} label={s.background_enabled ? "running" : "disabled"} />} />
              <KV k="Real sensor data" v={s.real_data_configured ? `received (last ${fmtDateTime(s.last_real_reading_received_at)})` : "none received yet"} />
              <KV k="Readings by source" v={JSON.stringify(s.readings_by_source)} mono />
              <KV k="Device ingestion auth" v={s.device_auth_required ? `required (per-device tokens${s.shared_device_key_configured ? " + shared key" : ""})` : "DISABLED"} />
              <KV k="Upload limit" v={`${s.max_upload_mb} MB`} />
              <KV k="User authentication" v={<span className="text-amber-300">{humanize(s.security.user_authentication)}</span>} />
              <Notice tone="warn" className="mt-2">{s.security.note}</Notice>
            </div>
          )}
        </Card>
        <Card title="Data source & display" bodyClass="space-y-3 p-3">
          <div className="flex items-center justify-between"><span className="text-xs">Dashboard data source</span>
            <Segmented value={s?.data_source.mode ?? "simulated"} onChange={(m) => setMode.mutate(m)} options={[{ value: "real", label: "Real" }, { value: "uploaded", label: "Uploaded" }, { value: "simulated", label: "Simulated" }, { value: "all", label: "All (labelled)" }]} />
          </div>
          <p className="text-[11px] text-slate-400">Real, uploaded and simulated data are stored separately and always labelled. “All” shows every source with its label; sources are never merged into one series.</p>
          <div className="flex items-center justify-between"><span className="text-xs">Reduced motion (disables pulsing markers & camera animation)</span>
            <input type="checkbox" checked={reducedMotion} onChange={(e) => setReducedMotion(e.target.checked)} aria-label="Reduced motion" /></div>
          <div className="label pt-2">API configuration</div>
          <KV k="API base" v={`${location.origin}/api/v1`} mono />
          <KV k="Docs" v={<a className="text-accent-soft hover:underline" href="/docs" target="_blank" rel="noreferrer">OpenAPI / Swagger UI</a>} />
          <KV k="Ingestion" v="POST /api/v1/ingest/readings · header X-Device-Token" mono />
        </Card>
        <MqttCard />
        {settings.data && <LimitsCard vibration={settings.data.vibration} environment={settings.data.environment} />}
        {settings.data?.priority_rules && <div className="xl:col-span-2"><PriorityRules value={settings.data.priority_rules} /></div>}
        <div id="rules" className="xl:col-span-2">
          <Card title="Alert rules" bodyClass="overflow-auto">
            {rules.isLoading ? <Loading /> : (
              <table className="table-base">
                <thead><tr><th>Rule</th><th>Enabled</th><th>Default priority</th><th>Cooldown (s)</th><th>Version</th></tr></thead>
                <tbody>{(rules.data ?? []).map((r) => <RuleRow key={r.id} r={r} />)}</tbody>
              </table>
            )}
          </Card>
        </div>
        <Card title="Model registry" actions={<button className="btn-ghost" onClick={() => reload.mutate(undefined)}><RefreshCw className="h-3.5 w-3.5" />Rescan models</button>} bodyClass="space-y-2 p-3">
          {models.data?.length ? models.data.map((m) => (
            <div key={m.id} className="rounded border border-white/10 p-2">
              <div className="flex items-center justify-between"><span className="mono text-accent-soft">{m.id} v{m.version}</span><span className="text-[11px]">{m.status}{m.is_active ? " · active" : ""}</span></div>
              <KV k="Task" v={`${m.task} · ${(m.categories ?? []).join(", ")}`} />
              <KV k="Threshold" v={m.threshold} />
              <KV k="Dataset" v={m.dataset ? JSON.stringify(m.dataset) : "not recorded"} mono />
              <KV k="Recorded metrics" v={m.metrics ? JSON.stringify(m.metrics) : "none recorded — treat outputs as unvalidated"} mono />
            </div>
          )) : (
            <Notice tone="warn">No trained model is installed. Inference is unavailable and no predictions are generated. Train and export a model with <code className="mono">backend/ml/train_crack_classifier.py</code>, evaluate it with <code className="mono">backend/ml/evaluate.py</code>, place it in <code className="mono">backend/model_store/&lt;name&gt;/</code> and rescan.</Notice>
          )}
          <p className="text-[11px] text-slate-500">AI-supported categories: {s?.models.ai_supported_categories.length ? s.models.ai_supported_categories.join(", ") : "none"}. Other categories can be recorded manually.</p>
        </Card>
        {settings.data && <JsonSetting k="device_status" title="Device status thresholds" value={settings.data.device_status} hint="Seconds since last real reading before a device is considered stale / offline." />}
        {settings.data && <JsonSetting k="vibration" title="Vibration analysis" value={settings.data.vibration} hint="Window length and anomaly-rule parameters (k·σ above baseline). Recorded with every evaluated window." />}
        {settings.data && <JsonSetting k="retention" title="Data retention" value={settings.data.retention} hint="Processed raw readings older than this are pruned (features are kept). Simulated raw data is pruned after 6 hours." />}
      </div>
    </div>
  );
}
