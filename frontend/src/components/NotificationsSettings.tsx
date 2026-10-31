import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Mail, MessageSquare, Send, Smartphone, Webhook } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "@/api/client";
import { fmtDateTime } from "@/lib/format";
import { PRIORITIES, PRIORITY_LABEL } from "@/lib/priority";
import { Card, Chip, Field, Notice } from "./ui";

type Channel = "telegram" | "email" | "sms" | "webhook";
interface NotifConfig {
  preferences: { enabled: boolean; min_priority: string; channels: Record<Channel, boolean>; include_simulated: boolean; rule_types: string[] };
  configured: Record<Channel, boolean>;
  fields: Record<Channel, Record<string, string | null>>;
}
interface LogRow { id: number; alert_id: string | null; channel: string; status: string; attempts: number; error: string | null; subject: string | null; is_test: boolean; created_at: string; sent_at: string | null }

const CHANNELS: { k: Channel; title: string; icon: typeof Send; help: string; fields: { key: string; label: string; secret?: boolean; placeholder?: string }[] }[] = [
  { k: "telegram", title: "Telegram (recommended — free, includes the crack photo)", icon: Send,
    help: "In Telegram, talk to @BotFather → /newbot → copy the token. Then send any message to your bot and open https://api.telegram.org/bot<token>/getUpdates to read your chat id. Group chats work too.",
    fields: [{ key: "telegram_bot_token", label: "Bot token", secret: true, placeholder: "123456789:AA…" }, { key: "telegram_chat_ids", label: "Chat id(s), comma-separated", placeholder: "123456789" }] },
  { k: "email", title: "Email", icon: Mail,
    help: "Any SMTP account. For Gmail: smtp.gmail.com, port 587, STARTTLS, and an App Password (Google Account → Security → App passwords).",
    fields: [{ key: "smtp_host", label: "SMTP server", placeholder: "smtp.gmail.com" }, { key: "smtp_port", label: "Port", placeholder: "587" },
      { key: "smtp_security", label: "Security (starttls | ssl | none)", placeholder: "starttls" }, { key: "smtp_user", label: "Username" },
      { key: "smtp_password", label: "Password / app password", secret: true }, { key: "smtp_from", label: "From address" }, { key: "smtp_to", label: "To (comma-separated)" }] },
  { k: "sms", title: "SMS (Twilio, paid)", icon: Smartphone,
    help: "Twilio console → Account SID + Auth Token, a Twilio phone number as sender, and recipient numbers in +91… format.",
    fields: [{ key: "twilio_account_sid", label: "Account SID", placeholder: "AC…" }, { key: "twilio_auth_token", label: "Auth token", secret: true },
      { key: "twilio_from", label: "From number", placeholder: "+1…" }, { key: "twilio_to", label: "To number(s)", placeholder: "+91…" }] },
  { k: "webhook", title: "Webhook (Discord, Slack, ntfy or your own server)", icon: Webhook,
    help: "Paste a Discord/Slack incoming-webhook URL or an ntfy topic URL (https://ntfy.sh/<your-topic> — free push notifications on your phone) and set the matching format.",
    fields: [{ key: "webhook_url", label: "URL", secret: true }, { key: "webhook_format", label: "Format (json | discord | slack | ntfy)", placeholder: "json" }] },
];

function ChannelCard({ ch, cfg, onSaved }: { ch: (typeof CHANNELS)[number]; cfg: NotifConfig; onSaved: () => void }) {
  const [vals, setVals] = useState<Record<string, string>>({});
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const current = cfg.fields[ch.k];
  const enabled = cfg.preferences.channels[ch.k];
  const actor = () => localStorage.getItem("ss.actor") || null;
  const save = async () => {
    setBusy(true);
    setMsg(null);
    try {
      await api("/notifications/config", { method: "PUT", json: { secrets: vals, actor: actor() } });
      setVals({});
      setMsg({ ok: true, text: "Saved" });
      onSaved();
    } catch (e) {
      setMsg({ ok: false, text: (e as Error).message });
    } finally {
      setBusy(false);
    }
  };
  const test = async () => {
    setBusy(true);
    setMsg(null);
    try {
      const r = await api<{ status: string; error: string | null }>(`/notifications/test?channel=${ch.k}`, { method: "POST" });
      setMsg(r.status === "sent" ? { ok: true, text: "Test message sent — check your phone/inbox." } : { ok: false, text: r.error ?? "failed" });
      onSaved();
    } catch (e) {
      setMsg({ ok: false, text: (e as Error).message });
    } finally {
      setBusy(false);
    }
  };
  const toggle = async () => {
    await api("/notifications/config", { method: "PUT", json: { preferences: { channels: { ...cfg.preferences.channels, [ch.k]: !enabled } }, actor: actor() } });
    onSaved();
  };
  const Icon = ch.icon;
  return (
    <Card title={<span className="flex items-center gap-1.5"><Icon className="h-3.5 w-3.5" />{ch.title}</span>}
      actions={<>
        {cfg.configured[ch.k] ? <Chip className="border-emerald-400/40 text-emerald-300">configured</Chip> : <Chip>not set up</Chip>}
        <label className="flex items-center gap-1 text-[11px] text-slate-300"><input type="checkbox" checked={enabled} onChange={toggle} />send</label>
      </>} bodyClass="space-y-2 p-3">
      <p className="text-[11px] text-slate-400">{ch.help}</p>
      <div className="grid grid-cols-2 gap-2">
        {ch.fields.map((f) => (
          <Field key={f.key} label={f.label}>
            <input className="input" type={f.secret ? "password" : "text"} autoComplete="off" value={vals[f.key] ?? ""}
              placeholder={current[f.key] ?? f.placeholder ?? ""} onChange={(e) => setVals({ ...vals, [f.key]: e.target.value })} aria-label={f.label} />
          </Field>
        ))}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <button className="btn-primary" disabled={busy || !Object.values(vals).some(Boolean)} onClick={save}>Save</button>
        <button className="btn-ghost" disabled={busy || !cfg.configured[ch.k]} onClick={test}><MessageSquare className="h-3.5 w-3.5" />Send test</button>
        {msg && <span className={`text-[11px] ${msg.ok ? "text-emerald-300" : "text-red-300"}`}>{msg.text}</span>}
      </div>
      <p className="text-[10px] text-slate-500">Saved secrets are never shown again (only their last characters). Leave a field empty to keep its current value.</p>
    </Card>
  );
}

export function NotificationsSettings() {
  const qc = useQueryClient();
  const cfg = useQuery({ queryKey: ["notif-config"], queryFn: () => api<NotifConfig>("/notifications/config") });
  const log = useQuery({ queryKey: ["notif-log"], queryFn: () => api<LogRow[]>("/notifications/log?limit=30"), refetchInterval: 10_000 });
  const [prefMsg, setPrefMsg] = useState<string | null>(null);
  const [prefs, setPrefs] = useState<NotifConfig["preferences"] | null>(null);
  useEffect(() => { if (cfg.data) setPrefs(cfg.data.preferences); }, [cfg.data]);
  const refresh = () => { qc.invalidateQueries({ queryKey: ["notif-config"] }); qc.invalidateQueries({ queryKey: ["notif-log"] }); };
  const savePrefs = async (p: NotifConfig["preferences"]) => {
    setPrefs(p);
    try {
      await api("/notifications/config", { method: "PUT", json: { preferences: p, actor: localStorage.getItem("ss.actor") || null } });
      setPrefMsg("Saved");
      refresh();
    } catch (e) {
      setPrefMsg((e as Error).message);
    }
  };
  if (!cfg.data || !prefs) return null;
  return (
    <div className="space-y-3">
      <Card title="When to send messages" bodyClass="space-y-3 p-3">
        <div className="flex flex-wrap items-center gap-4 text-xs">
          <label className="flex items-center gap-1.5"><input type="checkbox" checked={prefs.enabled} onChange={(e) => savePrefs({ ...prefs, enabled: e.target.checked })} />Send alert messages</label>
          <label className="flex items-center gap-1.5">From priority
            <select className="input w-40" value={prefs.min_priority} onChange={(e) => savePrefs({ ...prefs, min_priority: e.target.value })} aria-label="Minimum priority">
              {[...PRIORITIES].reverse().filter((p) => p !== "unassessed").map((p) => <option key={p} value={p}>{PRIORITY_LABEL[p]} and above</option>)}
            </select>
          </label>
          <label className="flex items-center gap-1.5"><input type="checkbox" checked={prefs.include_simulated} onChange={(e) => savePrefs({ ...prefs, include_simulated: e.target.checked })} />Also for simulated/demo data</label>
          {prefMsg && <span className="text-[11px] text-slate-400">{prefMsg}</span>}
        </div>
        <Notice>A message is sent when an alert is first raised (e.g. a crack found by the webcam, vibration above your limit, a sensor going offline), or when it escalates to
          your chosen priority. It includes where the crack is: its position in the photo, its point on the 3D model and GPS when the structure is geo-referenced — and Telegram/email attach the photo.</Notice>
      </Card>
      <div className="grid gap-3 xl:grid-cols-2">
        {CHANNELS.map((ch) => <ChannelCard key={ch.k} ch={ch} cfg={cfg.data!} onSaved={refresh} />)}
      </div>
      <Card title="Recent messages" bodyClass="max-h-72 overflow-auto">
        {!log.data?.length ? <div className="p-3 text-[11px] text-slate-500">No messages yet.</div> : (
          <table className="table-base">
            <thead><tr><th>When</th><th>Channel</th><th>Message</th><th>Status</th><th>Detail</th></tr></thead>
            <tbody>{log.data.map((r) => (
              <tr key={r.id}><td>{fmtDateTime(r.created_at)}</td><td>{r.channel}</td><td>{r.is_test ? "Test message" : r.subject}</td>
                <td className={r.status === "sent" ? "text-emerald-300" : r.status === "failed" ? "text-red-300" : "text-amber-300"}>{r.status}{r.attempts > 1 ? ` (${r.attempts} tries)` : ""}</td>
                <td className="text-[11px] text-slate-400">{r.error ?? (r.sent_at ? `sent ${fmtDateTime(r.sent_at)}` : "")}</td></tr>
            ))}</tbody>
          </table>
        )}
      </Card>
    </div>
  );
}
