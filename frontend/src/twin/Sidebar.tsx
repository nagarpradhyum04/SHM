import clsx from "clsx";
import { Camera, ChevronDown, ChevronRight, Cpu, Eye, Filter, Layers, ListTree, Search } from "lucide-react";
import { useMemo, useState } from "react";
import type { Component, Defect, Device, Priority } from "@/api/types";
import { ConnBadge } from "@/components/ui";
import { buildTree, focusForComponent, focusForDevice } from "@/lib/geometry";
import { CATEGORIES, PRIORITIES, PRIORITY_COLOR, PRIORITY_LABEL, REVIEW_STATUSES } from "@/lib/priority";
import { humanize } from "@/lib/format";
import { DEFAULT_FILTERS, type LayerKey, useUI } from "@/store/ui";

const LAYERS: { key: LayerKey; label: string; hint?: string }[] = [
  { key: "model", label: "Structure" },
  { key: "devices", label: "Sensors & cameras" },
  { key: "defects", label: "Defects" },
  { key: "boundaries", label: "Component boundaries" },
  { key: "heatmap", label: "Defect heatmap", hint: "Tints components by open findings, weighted by review priority" },
  { key: "wireframe", label: "Wireframe" },
  { key: "labels", label: "Labels" },
  { key: "history", label: "Historical findings", hint: "Include repaired/closed/false-positive findings" },
  { key: "coverage", label: "Camera coverage", hint: "Nominal field of view from configured camera pose (uncalibrated)" },
];

type Tab = "layers" | "components" | "devices" | "filters";
const CORE_LAYERS: LayerKey[] = ["model", "devices", "defects", "labels"];

function Toggle({ on, onClick, label, hint }: { on: boolean; onClick: () => void; label: string; hint?: string }) {
  return (
    <button role="switch" aria-checked={on} onClick={onClick} title={hint}
      className="flex w-full items-center justify-between rounded px-2 py-1.5 text-left text-xs text-slate-300 hover:bg-white/5">
      <span>{label}</span>
      <span className={clsx("relative h-4 w-7 rounded-full transition-colors", on ? "bg-accent/60" : "bg-white/10")}>
        <span className={clsx("absolute top-0.5 h-3 w-3 rounded-full bg-white transition-all", on ? "left-3.5" : "left-0.5")} />
      </span>
    </button>
  );
}

function TreeNode({ c, depth, tree, defectsByComp, query }: { c: Component; depth: number; tree: ReturnType<typeof buildTree>; defectsByComp: Map<string, Defect[]>; query: string }) {
  const kids = tree.children.get(c.id) ?? [];
  const [open, setOpen] = useState(depth === 0 && kids.length < 12);
  const selection = useUI((s) => s.selection);
  const select = useUI((s) => s.select);
  const camera = useUI((s) => s.camera);
  const setHover = useUI((s) => s.setHover);
  const matches = (x: Component): boolean =>
    !query || x.id.toLowerCase().includes(query) || x.name.toLowerCase().includes(query) || (tree.children.get(x.id) ?? []).some(matches);
  if (!matches(c)) return null;
  const count = (defectsByComp.get(c.id) ?? []).length + kids.reduce((n, k) => n + (defectsByComp.get(k.id) ?? []).length, 0);
  const selected = selection?.kind === "component" && selection.id === c.id;
  const geomComp = c.bbox ? c : null;
  return (
    <div>
      <div className={clsx("group flex items-center gap-1 rounded py-0.5 pr-1 text-xs", selected ? "bg-accent/15 text-accent-soft" : "text-slate-300 hover:bg-white/5")}
        style={{ paddingLeft: 4 + depth * 12 }} onMouseEnter={() => setHover(c.id)} onMouseLeave={() => setHover(null)}>
        {kids.length ? (
          <button aria-label={open ? "Collapse" : "Expand"} onClick={() => setOpen(!open)} className="text-slate-500 hover:text-white">
            {open || query ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
          </button>
        ) : <span className="w-3" />}
        <button className="min-w-0 flex-1 truncate text-left" title={`${c.name} (${c.id})`}
          onClick={() => {
            select({ kind: "component", id: c.id });
            if (geomComp) {
              const f = focusForComponent(geomComp);
              camera({ type: "focus", target: f.target, radius: f.radius });
            }
          }}>
          {c.name}
        </button>
        {count > 0 && <span className="rounded bg-orange-500/20 px-1 font-mono text-[9px] text-orange-300">{count}</span>}
      </div>
      {(open || query) && kids.map((k) => <TreeNode key={k.id} c={k} depth={depth + 1} tree={tree} defectsByComp={defectsByComp} query={query} />)}
    </div>
  );
}

export function Sidebar({ components, devices, defects }: { components: Component[]; devices: Device[]; defects: Defect[] }) {
  const [tab, setTab] = useState<Tab>("layers");
  const [query, setQuery] = useState("");
  const layers = useUI((s) => s.layers);
  const toggleLayer = useUI((s) => s.toggleLayer);
  const filters = useUI((s) => s.filters);
  const setFilters = useUI((s) => s.setFilters);
  const select = useUI((s) => s.select);
  const camera = useUI((s) => s.camera);
  const selection = useUI((s) => s.selection);
  const tree = useMemo(() => buildTree(components), [components]);
  const defectsByComp = useMemo(() => {
    const m = new Map<string, Defect[]>();
    defects.forEach((d) => d.component_id && m.set(d.component_id, [...(m.get(d.component_id) ?? []), d]));
    return m;
  }, [defects]);

  const toggleIn = <T extends string>(arr: T[], v: T) => (arr.includes(v) ? arr.filter((x) => x !== v) : [...arr, v]);
  const tabs: { k: Tab; icon: typeof Layers; label: string }[] = [
    { k: "layers", icon: Layers, label: "Layers" },
    { k: "components", icon: ListTree, label: "Components" },
    { k: "devices", icon: Cpu, label: "Devices" },
    { k: "filters", icon: Filter, label: "Filters" },
  ];

  return (
    <div className="flex h-full flex-col">
      <div className="flex border-b border-white/5" role="tablist">
        {tabs.map(({ k, icon: Icon, label }) => (
          <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)} title={label}
            className={clsx("flex flex-1 items-center justify-center gap-1 py-2 text-[11px]", tab === k ? "border-b-2 border-accent text-accent-soft" : "text-slate-400 hover:text-white")}>
            <Icon className="h-3.5 w-3.5" /><span className="hidden xl:inline">{label}</span>
          </button>
        ))}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-2">
        {tab === "layers" && (
          <div className="space-y-0.5">
            <div className="panel-title px-2 pb-1 pt-1">Show</div>
            {LAYERS.filter((l) => CORE_LAYERS.includes(l.key)).map((l) => <Toggle key={l.key} on={layers[l.key]} onClick={() => toggleLayer(l.key)} label={l.label} hint={l.hint} />)}
            <details className="pt-1">
              <summary className="cursor-pointer px-2 py-1 text-[11px] text-slate-400 hover:text-white">More view options</summary>
              {LAYERS.filter((l) => !CORE_LAYERS.includes(l.key)).map((l) => <Toggle key={l.key} on={layers[l.key]} onClick={() => toggleLayer(l.key)} label={l.label} hint={l.hint} />)}
            </details>
            <div className="panel-title px-2 pb-1 pt-4">Legend — review priority</div>
            {PRIORITIES.map((p) => (
              <div key={p} className="flex items-center gap-2 px-2 py-0.5 text-[11px] text-slate-300">
                <span className="h-2.5 w-2.5 rounded-full" style={{ background: PRIORITY_COLOR[p] }} />{PRIORITY_LABEL[p]}
              </div>
            ))}
            <div className="px-2 pt-2 text-[10px] leading-relaxed text-slate-500">
              ● surface-level location · ◆ component-level (exact position unknown) · ring = approximate.
              Colours indicate configured review priority, not certified structural safety.
            </div>
          </div>
        )}
        {tab === "components" && (
          <div>
            <div className="relative mb-2">
              <Search className="absolute left-2 top-2 h-3.5 w-3.5 text-slate-500" />
              <input className="input pl-7" placeholder="Search components…" value={query} onChange={(e) => setQuery(e.target.value.toLowerCase())} aria-label="Search components" />
            </div>
            {(tree.children.get(null) ?? []).map((c) => <TreeNode key={c.id} c={c} depth={0} tree={tree} defectsByComp={defectsByComp} query={query} />)}
          </div>
        )}
        {tab === "devices" && (
          <div className="space-y-3">
            {(["camera", "sensor"] as const).map((type) => (
              <div key={type}>
                <div className="panel-title flex items-center gap-1.5 px-1 pb-1">{type === "camera" ? <Camera className="h-3 w-3" /> : <Cpu className="h-3 w-3" />}{type === "camera" ? "Cameras" : "Sensors"}</div>
                {devices.filter((d) => (type === "camera") === (d.device_type === "camera")).map((d) => (
                  <button key={d.id} onClick={() => {
                    select({ kind: "device", id: d.id });
                    const f = focusForDevice(d);
                    camera({ type: "focus", target: f.target, radius: f.radius });
                  }}
                    className={clsx("mb-1 w-full rounded border px-2 py-1.5 text-left", selection?.id === d.id ? "border-accent/50 bg-accent/10" : "border-white/5 hover:bg-white/5")}>
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-mono text-[11px] text-slate-200">{d.id}</span>
                      <ConnBadge status={d.connection?.status} label={d.connection?.label} />
                    </div>
                    <div className="truncate text-[11px] text-slate-400">{d.name}</div>
                  </button>
                ))}
                {!devices.some((d) => (type === "camera") === (d.device_type === "camera")) && <div className="px-1 text-[11px] text-slate-500">None registered.</div>}
              </div>
            ))}
          </div>
        )}
        {tab === "filters" && (
          <div className="space-y-3 text-xs">
            <div>
              <div className="label mb-1">Review priority</div>
              <div className="flex flex-wrap gap-1">
                {PRIORITIES.map((p) => (
                  <button key={p} onClick={() => setFilters({ priorities: toggleIn(filters.priorities, p as Priority) })} aria-pressed={filters.priorities.includes(p)}
                    className={clsx("chip", filters.priorities.includes(p) ? "" : "opacity-50")} style={{ borderColor: `${PRIORITY_COLOR[p]}66`, color: PRIORITY_COLOR[p] }}>
                    {PRIORITY_LABEL[p]}
                  </button>
                ))}
              </div>
            </div>
            <div>
              <div className="label mb-1">Category</div>
              <div className="flex flex-wrap gap-1">
                {CATEGORIES.map((c) => (
                  <button key={c} onClick={() => setFilters({ categories: toggleIn(filters.categories, c) })} aria-pressed={filters.categories.includes(c)}
                    className={clsx("chip", filters.categories.includes(c) ? "border-accent/50 text-accent-soft" : "border-white/10 text-slate-400")}>{humanize(c)}</button>
                ))}
              </div>
            </div>
            <div>
              <div className="label mb-1">Review status</div>
              <div className="flex flex-wrap gap-1">
                {REVIEW_STATUSES.map((s) => (
                  <button key={s} onClick={() => setFilters({ statuses: toggleIn(filters.statuses, s) })} aria-pressed={filters.statuses.includes(s)}
                    className={clsx("chip", filters.statuses.includes(s) ? "border-accent/50 text-accent-soft" : "border-white/10 text-slate-400")}>{humanize(s)}</button>
                ))}
              </div>
            </div>
            <div>
              <div className="label mb-1">Data source</div>
              <div className="flex flex-wrap gap-1">
                {["real", "uploaded", "demo", "simulated"].map((s) => (
                  <button key={s} onClick={() => setFilters({ sources: toggleIn(filters.sources, s) })} aria-pressed={filters.sources.includes(s)}
                    className={clsx("chip", filters.sources.includes(s) ? "border-accent/50 text-accent-soft" : "border-white/10 text-slate-400")}>{humanize(s)}</button>
                ))}
              </div>
            </div>
            <div>
              <div className="label mb-1">Observed since</div>
              <input type="date" className="input" value={filters.since ? filters.since.slice(0, 10) : ""} aria-label="Observed since"
                onChange={(e) => setFilters({ since: e.target.value ? new Date(e.target.value).toISOString() : null })} />
            </div>
            <button className="btn-ghost w-full justify-center" onClick={() => setFilters(DEFAULT_FILTERS)}><Eye className="h-3.5 w-3.5" />Reset filters</button>
          </div>
        )}
      </div>
    </div>
  );
}
