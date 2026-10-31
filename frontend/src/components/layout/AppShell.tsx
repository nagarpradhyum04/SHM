import clsx from "clsx";
import {
  Activity, Bell, Box, Building2, ChevronsLeft, ChevronsRight, ClipboardCheck, Cpu, FileText, Hourglass, History, Settings, ShieldAlert, Waves,
} from "lucide-react";
import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useAlerts, useAssets, useSystemStatus } from "@/api/hooks";
import { useEventStream } from "@/hooks/useEventStream";
import { useUI } from "@/store/ui";

export const NAV = [
  { to: "/twin", label: "Digital Twin", short: "3D Twin", icon: Box, group: "Monitor" },
  { to: "/alerts", label: "Alerts Center", short: "Alerts", icon: Bell, group: "Monitor" },
  { to: "/sensors", label: "Sensor Analytics", short: "Sensors", icon: Waves, group: "Monitor" },
  { to: "/defects", label: "Defect Registry", short: "Defects", icon: ShieldAlert, group: "Inspect" },
  { to: "/inspections", label: "Inspections", short: "Inspections", icon: ClipboardCheck, group: "Inspect" },
  { to: "/rul", label: "Remaining Life", short: "Remaining life", icon: Hourglass, group: "Analyse" },
  { to: "/history", label: "Historical Analysis", short: "History", icon: History, group: "Analyse" },
  { to: "/reports", label: "Reports", short: "Reports", icon: FileText, group: "Analyse" },
  { to: "/devices", label: "Device Registry", short: "Devices", icon: Cpu, group: "Set up" },
  { to: "/assets", label: "Infrastructure Assets", short: "Structures", icon: Building2, group: "Set up" },
  { to: "/settings", label: "Settings & System Health", short: "Settings", icon: Settings, group: "Set up" },
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
  const [navOpen, setNavOpen] = useState(() => { try { return localStorage.getItem("ss.nav") !== "collapsed"; } catch { return true; } });
  const toggleNav = () => { setNavOpen(!navOpen); try { localStorage.setItem("ss.nav", navOpen ? "collapsed" : "open"); } catch { /* ignore */ } };

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
          <div className="hidden leading-none sm:block">
            <div className="whitespace-nowrap text-[13px] font-semibold tracking-wide text-white">StructuraSense <span className="text-accent">AI</span></div>
            <div className="hidden whitespace-nowrap text-[9px] uppercase tracking-[0.2em] text-slate-500 xl:block">Structural health monitoring</div>
          </div>
        </div>
        <div className="h-6 w-px bg-white/10" />
        <label className="flex items-center gap-2">
          <span className="sr-only">Infrastructure asset</span>
          <select aria-label="Infrastructure asset" className="input w-40 py-1 md:w-64" value={assetId ?? ""} onChange={(e) => setAsset(e.target.value)}>
            {!assets?.length && <option value="">No assets registered</option>}
            {assets?.map((a) => (
              <option key={a.id} value={a.id}>{a.name}{a.is_demo ? " (demo)" : ""}</option>
            ))}
          </select>
        </label>
        {assets?.find((a) => a.id === assetId)?.is_demo && (
          <span className="chip hidden border-violet-400/40 bg-violet-400/10 text-violet-300 md:inline-flex" title="Procedural model and synthetic/simulated data">Demonstration asset</span>
        )}
        <span className="hidden text-xs text-slate-400 lg:inline">/ {current?.label ?? ""}</span>
        <div className="flex-1" />
        <button className="chip hidden border-white/15 text-slate-400 hover:text-white md:inline-flex" onClick={() => nav("/settings#data")}
          title="Which data the dashboards show — change in Settings">Data: {mode === "all" ? "all (labelled)" : mode}</button>
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
        <nav aria-label="Primary" className={clsx("z-10 flex shrink-0 flex-col gap-0.5 overflow-y-auto border-r border-accent/10 bg-ink-950/80 py-2", navOpen ? "w-48 px-2" : "w-14 items-center")}>
          {NAV.map(({ to, label, short, icon: Icon, group }, i) => (
            <div key={to} className={navOpen ? "" : "flex justify-center"}>
              {navOpen && (i === 0 || NAV[i - 1].group !== group) && <div className="px-2 pb-1 pt-3 text-[9px] font-semibold uppercase tracking-[0.18em] text-slate-500 first:pt-0">{group}</div>}
              <NavLink to={to} title={label} aria-label={label}
                className={({ isActive }) => clsx("relative flex items-center gap-2.5 rounded-lg transition-colors", navOpen ? "h-9 px-2.5" : "h-10 w-10 justify-center",
                  isActive ? "bg-accent/15 text-accent shadow-glow" : "text-slate-400 hover:bg-white/5 hover:text-slate-100")}>
                <Icon className="h-[18px] w-[18px] shrink-0" />
                {navOpen && <span className="truncate text-[13px]">{short}</span>}
                {to === "/alerts" && nOpen > 0 && (navOpen
                  ? <span className={clsx("ml-auto rounded-full px-1.5 text-[10px] font-bold text-white", highOpen ? "bg-red-500" : "bg-orange-500")}>{nOpen}</span>
                  : <span className="absolute right-1.5 top-1.5 h-1.5 w-1.5 rounded-full bg-orange-400" />)}
              </NavLink>
            </div>
          ))}
          <div className="flex-1" />
          <button onClick={toggleNav} className={clsx("flex items-center gap-2 rounded-lg py-2 text-[11px] text-slate-500 hover:text-white", navOpen ? "px-2.5" : "justify-center")}
            aria-label={navOpen ? "Collapse menu" : "Expand menu"}>
            {navOpen ? <><ChevronsLeft className="h-4 w-4" />Collapse</> : <ChevronsRight className="h-4 w-4" />}
          </button>
          <Activity className={clsx("mx-auto mb-1 h-4 w-4", backendOk ? "text-emerald-400/70" : "text-red-400")} aria-hidden />
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
