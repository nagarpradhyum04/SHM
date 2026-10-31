import clsx from "clsx";
import { Crosshair, Expand, Eye, Maximize2, PanelBottom, PanelLeft, PanelRight, RotateCcw, Video } from "lucide-react";
import { lazy, Suspense, useEffect, useMemo } from "react";
import { useAssets, useComponents, useDefects, useDevices, useSummary } from "@/api/hooks";
import { API_BASE } from "@/api/client";
import { ErrorState, Loading, Stat } from "@/components/ui";
import { fmtAgo } from "@/lib/format";
import { applyDefectFilters, componentHeat, focusForComponent, focusForDefect, focusForDevice, sceneBounds } from "@/lib/geometry";
import { useUI } from "@/store/ui";
import { DetailsPanel } from "@/twin/Details";
import { Sidebar } from "@/twin/Sidebar";
import { Timeline } from "@/twin/Timeline";

const BridgeScene = lazy(() => import("@/twin/BridgeScene"));

function SummaryStrip({ assetId, shownDefects }: { assetId: string; shownDefects: number }) {
  const s = useSummary(assetId);
  if (!s.data) return null;
  const d = s.data;
  return (
    <div className="panel pointer-events-auto grid grid-cols-3 gap-x-6 gap-y-2 px-4 py-2.5 lg:grid-cols-6">
      <Stat label="Components" value={d.components} />
      <Stat label="Findings" value={d.open_findings} hint={`${shownDefects} shown with current filters`} />
      <Stat label="High priority" value={d.high_priority_reviews} tone={d.high_priority_reviews ? "crit" : undefined} />
      <Stat label="Devices online" value={`${d.devices_online_real}${d.devices_stale + d.devices_offline ? ` · ${d.devices_stale + d.devices_offline} down` : ""}`}
        hint={`${d.devices_online_real} real online · ${d.devices_stale} stale · ${d.devices_offline} offline · ${d.devices_simulated} simulated · ${d.devices_never_connected} never connected`}
        tone={d.devices_stale + d.devices_offline ? "warn" : d.devices_online_real ? "ok" : "muted"} />
      <Stat label="Alerts open" value={d.alerts_open} tone={d.alerts_high_unresolved ? "crit" : d.alerts_open ? "warn" : undefined} />
      <Stat label="Last inspection" value={d.latest_inspection_at ? fmtAgo(d.latest_inspection_at) : "none"} />
    </div>
  );
}

function ViewControls() {
  const camera = useUI((s) => s.camera);
  const selection = useUI((s) => s.selection);
  const btn = "flex h-8 items-center gap-1 rounded-md px-2 text-[11px] text-slate-300 hover:bg-accent/15 hover:text-accent-soft";
  return (
    <div className="panel pointer-events-auto flex flex-wrap items-center gap-0.5 p-1">
      <button className={btn} onClick={() => camera({ type: "reset" })} title="Reset camera"><RotateCcw className="h-3.5 w-3.5" /></button>
      <button className={btn} onClick={() => camera({ type: "fit" })} title="Fit entire bridge"><Maximize2 className="h-3.5 w-3.5" /></button>
      <span className="mx-1 h-5 w-px bg-white/10" />
      {(["perspective", "front", "side", "top"] as const).map((v) => (
        <button key={v} className={btn} onClick={() => camera({ type: "view", view: v })}>{v[0].toUpperCase() + v.slice(1)}</button>
      ))}
      <span className="mx-1 h-5 w-px bg-white/10" />
      <button className={clsx(btn, !selection && "pointer-events-none opacity-40")} onClick={() => window.dispatchEvent(new CustomEvent("twin:focus-selection"))} title="Focus selection"><Crosshair className="h-3.5 w-3.5" />Focus</button>
    </div>
  );
}

export default function DigitalTwin() {
  const assetId = useUI((s) => s.assetId);
  const filters = useUI((s) => s.filters);
  const layers = useUI((s) => s.layers);
  const { leftOpen, rightOpen, timelineOpen, togglePanel, pickMode, pickPurpose, setPickMode } = useUI();
  const selection = useUI((s) => s.selection);
  const focusRequest = useUI((s) => s.focusRequest);
  const camera = useUI((s) => s.camera);

  const comps = useComponents(assetId ?? undefined);
  const assets = useAssets();
  const asset = assets.data?.find((a) => a.id === assetId);
  const modelKind = asset?.model_kind === "gltf" ? "gltf" : "procedural";
  const modelUrl = modelKind === "gltf" ? `${API_BASE}/assets/${assetId}/model/file?v=${encodeURIComponent(asset?.model_meta?.uploaded_at ?? "")}` : undefined;
  const devices = useDevices(assetId ?? undefined);
  const defects = useDefects({ asset_id: assetId ?? undefined }, !!assetId);

  const componentMap = useMemo(() => new Map((comps.data ?? []).map((c) => [c.id, c])), [comps.data]);
  const shown = useMemo(() => applyDefectFilters(defects.data ?? [], filters, layers.history), [defects.data, filters, layers.history]);
  const bounds = useMemo(() => sceneBounds(comps.data ?? [], modelKind === "gltf" ? asset?.model_meta?.bounds : null), [comps.data, modelKind, asset?.model_meta?.bounds]);
  const heat = useMemo(() => (layers.heatmap ? componentHeat(shown.filter((d) => !["repaired", "closed", "false_positive"].includes(d.review_status))) : null), [shown, layers.heatmap]);

  // Focus the camera on the current selection (button, external navigation via requestFocus).
  const focusSelection = (sel = selection) => {
    if (!sel) return;
    if (sel.kind === "component") {
      const c = componentMap.get(sel.id);
      if (c?.bbox) camera({ type: "focus", ...focusForComponent(c) });
    } else if (sel.kind === "device") {
      const d = devices.data?.find((x) => x.id === sel.id);
      if (d) camera({ type: "focus", ...focusForDevice(d) });
    } else {
      const d = defects.data?.find((x) => x.id === sel.id);
      if (d) {
        const f = focusForDefect(d, d.component_id ? componentMap.get(d.component_id) : null);
        if (f) camera({ type: "focus", ...f });
      }
    }
  };
  useEffect(() => {
    const h = () => focusSelection();
    window.addEventListener("twin:focus-selection", h);
    return () => window.removeEventListener("twin:focus-selection", h);
  });
  useEffect(() => {
    if (focusRequest && comps.data && devices.data && defects.data) {
      const t = setTimeout(() => focusSelection(focusRequest), 150);
      return () => clearTimeout(t);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focusRequest?.nonce, !!comps.data, !!devices.data, !!defects.data]);
  // Focus on defect markers selected by clicking.
  useEffect(() => {
    if (selection?.kind === "defect") focusSelection();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selection?.kind === "defect" ? selection.id : null]);

  if (!assetId) return <Loading label="Loading assets…" />;
  const err = comps.error || devices.error || defects.error;

  return (
    <div className="relative flex h-full">
      {leftOpen && (
        <aside className="panel-solid z-30 m-2 mr-0 w-72 shrink-0 overflow-hidden rounded-lg max-lg:absolute max-lg:inset-y-0 max-lg:left-0 max-lg:shadow-glow" aria-label="Model controls">
          <Sidebar components={comps.data ?? []} devices={devices.data ?? []} defects={shown} />
        </aside>
      )}
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="relative m-2 min-h-0 flex-1 overflow-hidden rounded-lg border border-accent/15 bg-ink-950">
          {err ? <ErrorState error={err} /> : comps.isLoading ? <Loading label="Loading structural model…" /> : (
            <Suspense fallback={<Loading label="Initialising 3D viewer…" />}>
              <BridgeScene components={comps.data ?? []} componentMap={componentMap} devices={devices.data ?? []} defects={shown} heat={heat}
                modelKind={modelKind} modelUrl={modelUrl} bounds={bounds} />
            </Suspense>
          )}
          <div className="pointer-events-none absolute inset-x-2 top-2 flex items-start justify-between gap-2">
            <SummaryStrip assetId={assetId} shownDefects={shown.length} />
          </div>
          <div className="pointer-events-none absolute bottom-2 left-2 flex gap-1">
            <div className="panel pointer-events-auto flex gap-0.5 p-1">
              <button className="rounded p-1.5 text-slate-300 hover:bg-white/5" onClick={() => togglePanel("leftOpen")} aria-label="Toggle left panel" title="Toggle left panel"><PanelLeft className="h-3.5 w-3.5" /></button>
              <button className="rounded p-1.5 text-slate-300 hover:bg-white/5" onClick={() => togglePanel("timelineOpen")} aria-label="Toggle timeline" title="Toggle timeline"><PanelBottom className="h-3.5 w-3.5" /></button>
              <button className="rounded p-1.5 text-slate-300 hover:bg-white/5" onClick={() => togglePanel("rightOpen")} aria-label="Toggle details panel" title="Toggle details panel"><PanelRight className="h-3.5 w-3.5" /></button>
            </div>
            <div className="panel pointer-events-auto hidden items-center gap-2 px-2 text-[10px] text-slate-400 md:flex">
              <Eye className="h-3 w-3" /> {modelKind === "gltf" ? `Uploaded model: ${asset?.model_meta?.filename ?? "GLB"}` : "Procedural development model — not a surveyed representation."}
            </div>
          </div>
          <div className="pointer-events-none absolute bottom-2 right-2"><ViewControls /></div>
          {pickMode && (
            <div className="absolute left-1/2 top-24 flex -translate-x-1/2 items-center gap-2 rounded-md border border-accent/50 bg-ink-950/95 px-3 py-2 text-xs text-accent-soft shadow-glow">
              <Video className="h-3.5 w-3.5" /> {{ finding: "Click a point on the structure to record an approximate surface location.",
                device_position: "Click the structure where the device is installed.", device_aim: "Click the point the camera should look at." }[pickPurpose]}
              <button className="btn-ghost" onClick={() => setPickMode(false)}>Cancel</button>
            </div>
          )}
          {!rightOpen && selection && (
            <button className="btn-primary absolute right-2 top-24" onClick={() => togglePanel("rightOpen")}><Expand className="h-3.5 w-3.5" />Details</button>
          )}
        </div>
        {timelineOpen && <div className="panel-solid mx-2 mb-2 h-36 shrink-0"><Timeline assetId={assetId} /></div>}
      </div>
      {rightOpen && (
        <aside className="panel-solid z-30 m-2 ml-0 w-[380px] max-w-[calc(100vw-5rem)] shrink-0 overflow-hidden max-lg:absolute max-lg:inset-y-0 max-lg:right-0 max-lg:shadow-glow" aria-label="Details">
          <DetailsPanel assetId={assetId} components={componentMap} devices={devices.data ?? []} />
        </aside>
      )}
    </div>
  );
}
