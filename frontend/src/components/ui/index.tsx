import clsx from "clsx";
import { AlertTriangle, Inbox, Loader2, X } from "lucide-react";
import type { ReactNode } from "react";
import type { Priority } from "@/api/types";
import { CONNECTION_COLOR, PRIORITY_COLOR, PRIORITY_LABEL, SOURCE_STYLE } from "@/lib/priority";
import { humanize } from "@/lib/format";

export function PriorityBadge({ p, className }: { p: Priority | string; className?: string }) {
  const c = PRIORITY_COLOR[p as Priority] ?? "#94a3b8";
  return (
    <span className={clsx("chip", className)} style={{ borderColor: `${c}66`, color: c, background: `${c}14` }} title="Review priority (not a certified severity rating)">
      <span className="h-1.5 w-1.5 rounded-full" style={{ background: c }} />
      {PRIORITY_LABEL[p as Priority] ?? p}
    </span>
  );
}

export function SourceBadge({ source, className }: { source?: string | null; className?: string }) {
  if (!source) return null;
  const s = SOURCE_STYLE[source] ?? { label: source, cls: "border-white/20 text-slate-300" };
  return <span className={clsx("chip", s.cls, className)} title={`Data source: ${s.label}`}>{s.label}</span>;
}

export function ConnBadge({ status, label }: { status?: string; label?: string }) {
  const c = CONNECTION_COLOR[status ?? ""] ?? "#64748b";
  return (
    <span className="chip" style={{ borderColor: `${c}55`, color: c }} title={label}>
      <span className="h-1.5 w-1.5 rounded-full" style={{ background: c }} />
      {humanize(status)}
    </span>
  );
}

export function Chip({ children, className, title }: { children: ReactNode; className?: string; title?: string }) {
  return <span title={title} className={clsx("chip border-white/15 text-slate-300", className)}>{children}</span>;
}

export function Loading({ label = "Loading…", className }: { label?: string; className?: string }) {
  return (
    <div role="status" className={clsx("flex items-center gap-2 p-4 text-xs text-slate-400", className)}>
      <Loader2 className="h-4 w-4 animate-spin text-accent" /> {label}
    </div>
  );
}

export function ErrorState({ error, onRetry, className }: { error: unknown; onRetry?: () => void; className?: string }) {
  const msg = error instanceof Error ? error.message : String(error);
  return (
    <div role="alert" className={clsx("m-3 flex items-start gap-2 rounded-md border border-red-400/30 bg-red-500/10 p-3 text-xs text-red-200", className)}>
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
      <div className="flex-1">{msg}</div>
      {onRetry && <button className="btn-ghost" onClick={onRetry}>Retry</button>}
    </div>
  );
}

export function Empty({ title, children, className }: { title: string; children?: ReactNode; className?: string }) {
  return (
    <div className={clsx("flex flex-col items-center justify-center gap-1 p-6 text-center text-xs text-slate-400", className)}>
      <Inbox className="h-5 w-5 text-slate-500" />
      <div className="font-medium text-slate-300">{title}</div>
      {children && <div className="max-w-sm">{children}</div>}
    </div>
  );
}

export function Stat({ label, value, hint, tone }: { label: string; value: ReactNode; hint?: string; tone?: "warn" | "crit" | "ok" | "muted" }) {
  const color = tone === "crit" ? "text-red-300" : tone === "warn" ? "text-amber-300" : tone === "ok" ? "text-emerald-300" : tone === "muted" ? "text-slate-500" : "text-slate-100";
  return (
    <div className="min-w-0" title={hint}>
      <div className="truncate text-[10px] uppercase tracking-wider text-slate-400">{label}</div>
      <div className={clsx("font-mono text-base font-medium leading-tight", color)}>{value}</div>
    </div>
  );
}

export function Card({ title, actions, children, className, bodyClass }: { title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string; bodyClass?: string }) {
  return (
    <section className={clsx("panel flex min-h-0 flex-col", className)}>
      {(title || actions) && (
        <header className="flex items-center justify-between gap-2 border-b border-white/5 px-3 py-2">
          <h2 className="panel-title">{title}</h2>
          <div className="flex items-center gap-1.5">{actions}</div>
        </header>
      )}
      <div className={clsx("min-h-0 flex-1", bodyClass)}>{children}</div>
    </section>
  );
}

export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return (
    <label className="block space-y-1">
      <span className="label">{label}</span>
      {children}
      {hint && <span className="block text-[10px] text-slate-500">{hint}</span>}
    </label>
  );
}

export function KV({ k, v, mono }: { k: string; v: ReactNode; mono?: boolean }) {
  return (
    <div className="grid grid-cols-[110px_1fr] gap-2 py-0.5 text-xs">
      <div className="text-slate-400">{k}</div>
      <div className={clsx("min-w-0 break-words text-slate-200", mono && "mono")}>{v ?? "—"}</div>
    </div>
  );
}

export function Modal({ title, onClose, children, wide }: { title: string; onClose: () => void; children: ReactNode; wide?: boolean }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onMouseDown={onClose}>
      <div role="dialog" aria-label={title} className={clsx("panel-solid max-h-[90vh] w-full overflow-auto shadow-glow", wide ? "max-w-4xl" : "max-w-lg")} onMouseDown={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between border-b border-white/10 px-4 py-2.5">
          <h2 className="text-sm font-semibold">{title}</h2>
          <button aria-label="Close" className="text-slate-400 hover:text-white" onClick={onClose}><X className="h-4 w-4" /></button>
        </div>
        <div className="p-4">{children}</div>
      </div>
    </div>
  );
}

export function Notice({ tone = "info", children, className }: { tone?: "info" | "warn"; children: ReactNode; className?: string }) {
  return (
    <div className={clsx("rounded-md border px-3 py-2 text-[11px] leading-relaxed",
      tone === "warn" ? "border-amber-400/30 bg-amber-400/5 text-amber-200" : "border-accent/20 bg-accent/5 text-slate-300", className)}>
      {children}
    </div>
  );
}

export function Segmented<T extends string>({ value, options, onChange, size = "sm" }: { value: T; options: { value: T; label: string }[]; onChange: (v: T) => void; size?: "sm" | "xs" }) {
  return (
    <div className="inline-flex rounded-md border border-white/10 bg-ink-950/60 p-0.5" role="radiogroup">
      {options.map((o) => (
        <button key={o.value} role="radio" aria-checked={value === o.value} onClick={() => onChange(o.value)}
          className={clsx("rounded px-2 font-medium transition-colors", size === "xs" ? "py-0.5 text-[10px]" : "py-1 text-[11px]",
            value === o.value ? "bg-accent/20 text-accent-soft" : "text-slate-400 hover:text-slate-200")}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-3 px-5 pb-3 pt-4">
      <div>
        <h1 className="text-lg font-semibold tracking-tight text-white">{title}</h1>
        {subtitle && <p className="mt-0.5 text-xs text-slate-400">{subtitle}</p>}
      </div>
      <div className="flex flex-wrap items-center gap-2">{actions}</div>
    </div>
  );
}
