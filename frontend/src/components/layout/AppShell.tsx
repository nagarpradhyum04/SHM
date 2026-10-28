import clsx from "clsx";
import {
  Activity, Bell, Box, Building2, ClipboardCheck, Cpu, FileText, History, Settings, ShieldAlert, Waves,
} from "lucide-react";
import { useEffect } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useAlerts, useAssets, useSystemStatus, useApiMutation } from "@/api/hooks";
import { api } from "@/api/client";
import { useEventStream } from "@/hooks/useEventStream";
import { useUI } from "@/store/ui";
import { Segmented } from "@/components/ui";

export const NAV = [
  { to: "/twin", label: "Digital Twin", icon: Box },
  { to: "/assets", label: "Infrastructure Assets", icon: Building2 },
  { to: "/inspections", label: "Inspections", icon: ClipboardCheck },
  { to: "/defects", label: "Defect Registry", icon: ShieldAlert },
  { to: "/devices", label: "Device Registry", icon: Cpu },
  { to: "/sensors", label: "Sensor Analytics", icon: Waves },
  { to: "/alerts", label: "Alerts Center", icon: Bell },
  { to: "/history", label: "Historical Analysis", icon: History },
  { to: "/reports", label: "Reports", icon: FileText },
  { to: "/settings", label: "Settings & System Health", icon: Settings },
];

function Logo() {
  return (
    <svg viewBox="0 0 32 32" className="h-6 w-6" aria-hidden>
      <path d="M2 22h28M6 22 16 6l10 16M16 6v16M11 14l5-8 5 8" stroke="#22d3ee" strokeWidth="2" fill="none" />
    </svg>
  );
}

export function AppShell() {
  const { data: assets } = useAssets();
  const assetId = useUI((s) => s.assetId);
  const setAsset = useUI((s) => s.setAsset);
  const reducedMotion = useUI((s) => s.reducedMotion);
  const stream = useEventStream();
  const status = useSystemStatus();
  const loc = useLocation();
  const nav = useNavigate();
  const openAlerts = useAlerts({ asset_id: assetId ?? undefined, status: ["open"] });
  const setMode = useApiMutation((mode: string) => api("/settings/data_source", { method: "PUT", json: { value: { mode } } }), ["system-status", "settings"]);

  useEffect(() => {
    if (assets?.length && (!assetId || !assets.some((a) => a.id === assetId))) setAsset(assets[0].id);
  }, [assets, assetId, setAsset]);

  useEffect(() => {
    document.documentElement.classList.toggle("reduced-motion", reducedMotion);
  }, [reducedMotion]);

  const current = NAV.find((n) => loc.pathname.startsWith(n.to));
  const backendOk = status.isSuccess && status.data.database.ok;
  const mode = status.data?.data_source.mode ?? "simulated";
  const nOpen = openAlerts.data?.length ?? 0;
  const highOpen = openAlerts.data?.filter((a) => a.priority === "high" || a.priority === "critical").length ?? 0;

  return (
    <div className="flex h-full flex-col">
      <header className="z-20 flex h-12 shrink-0 items-center gap-3 border-b border-accent/10 bg-ink-950/90 px-3 backdrop-blur">
        <div className="flex items-center gap-2 pr-2">
          <Logo />
          <div className="leading-none">
            <div className="text-[13px] font-semibold tracking-wide text-white">StructuraSense <span className="text-accent">AI</span></div>
            <div className="text-[9px] uppercase tracking-[0.2em] text-slate-500">Structural health monitoring</div>
          </div>
        </div>
        <div className="h-6 w-px bg-white/10" />
        <label className="flex items-center gap-2">
          <span className="sr-only">Infrastructure asset</span>
          <select aria-label="Infrastructure asset" className="input w-64 py-1" value={assetId ?? ""} onChange={(e) => setAsset(e.target.value)}>
            {!assets?.length && <option value="">No assets registered</option>}
            {assets?.map((a) => (
              <option key={a.id} value={a.id}>{a.name}{a.is_demo ? " (demo)" : ""}</option>
            ))}
          </select>
        </label>
        {assets?.find((a) => a.id === assetId)?.is_demo && (
          <span className="chip border-violet-400/40 bg-violet-400/10 text-violet-300" title="Procedural model and synthetic/simulated data">Demonstration asset</span>
        )}
        <span className="hidden text-xs text-slate-400 lg:inline">/ {current?.label ?? ""}</span>
        <div className="flex-1" />
        <div className="hidden items-center gap-2 md:flex" title="Which sensor data sources dashboards display. Sources are always labelled.">
          <span className="label">Data</span>
          <Segmented value={mode} onChange={(m) => setMode.mutate(m)} size="xs"
            options={[{ value: "real", label: "Real" }, { value: "uploaded", label: "Uploaded" }, { value: "simulated", label: "Simulated" }, { value: "all", label: "All" }]} />
        </div>
        <div className="flex items-center gap-1.5 text-[11px]" title={backendOk ? `API ${stream === "open" ? "connected · live updates on" : "connected · live updates unavailable"}` : "Backend unreachable"}>
          <span className={clsx("h-2 w-2 rounded-full", backendOk ? (stream === "open" ? "bg-emerald-400" : "bg-amber-400") : "bg-red-500")} />
          <span className="hidden text-slate-400 sm:inline">{backendOk ? (stream === "open" ? "Live" : "API") : status.isLoading ? "Connecting" : "Offline"}</span>
        </div>
        <button className="relative rounded-md p-1.5 text-slate-300 hover:bg-white/5" aria-label={`${nOpen} open alerts`} onClick={() => nav("/alerts")}>
          <Bell className="h-4 w-4" />
          {nOpen > 0 && (
            <span className={clsx("absolute -right-0.5 -top-0.5 min-w-[16px] rounded-full px-1 text-center text-[9px] font-bold leading-4 text-white", highOpen ? "bg-red-500" : "bg-orange-500")}>{nOpen}</span>
          )}
        </button>
        <button className="rounded-md p-1.5 text-slate-300 hover:bg-white/5" aria-label="Settings" onClick={() => nav("/settings")}><Settings className="h-4 w-4" /></button>
      </header>
      <div className="flex min-h-0 flex-1">
        <nav aria-label="Primary" className="z-10 flex w-14 shrink-0 flex-col items-center gap-1 border-r border-accent/10 bg-ink-950/80 py-2">
          {NAV.map(({ to, label, icon: Icon }) => (
            <NavLink key={to} to={to} title={label} aria-label={label}
              className={({ isActive }) => clsx("group relative flex h-10 w-10 items-center justify-center rounded-lg transition-colors",
                isActive ? "bg-accent/15 text-accent shadow-glow" : "text-slate-400 hover:bg-white/5 hover:text-slate-100")}>
              <Icon className="h-[18px] w-[18px]" />
              {to === "/alerts" && nOpen > 0 && <span className="absolute right-1.5 top-1.5 h-1.5 w-1.5 rounded-full bg-orange-400" />}
            </NavLink>
          ))}
          <div className="flex-1" />
          <Activity className={clsx("mb-2 h-4 w-4", backendOk ? "text-emerald-400/70" : "text-red-400")} aria-hidden />
        </nav>
        <main className="min-w-0 flex-1 overflow-hidden">
          {status.isError && (
            <div role="alert" className="border-b border-red-400/30 bg-red-500/10 px-4 py-1.5 text-xs text-red-200">
              Backend unreachable — start it with <code className="mono">./scripts/dev.sh</code> or <code className="mono">uvicorn app.main:app</code>. Data shown may be outdated.
            </div>
          )}
          <Outlet />
        </main>
      </div>
    </div>
  );
}
