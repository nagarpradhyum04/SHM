import { Building2, MapPin, Plus } from "lucide-react";
import { lazy, Suspense, useMemo, useState } from "react";
import { api } from "@/api/client";
import { useApiMutation, useAssets, useComponents, useSummary } from "@/api/hooks";
import type { Asset } from "@/api/types";
import { Card, Chip, Empty, ErrorState, Field, KV, Loading, Modal, Notice, PageHeader } from "@/components/ui";
import { ModelUpload } from "@/components/ModelUpload";
import { useShowIn3D } from "@/hooks/useShowIn3D";
import { fmtDate, fmtDateTime, humanize } from "@/lib/format";
import { useUI } from "@/store/ui";

const AssetMap = lazy(() => import("@/components/AssetMap"));
const TILE_URL = import.meta.env.VITE_MAP_TILE_URL as string | undefined;

function AssetForm({ initial, onDone }: { initial?: Asset; onDone: () => void }) {
  const [f, setF] = useState({
    id: initial?.id ?? "", name: initial?.name ?? "", asset_type: initial?.asset_type ?? "bridge", description: initial?.description ?? "",
    latitude: initial?.latitude?.toString() ?? "", longitude: initial?.longitude?.toString() ?? "", site_description: initial?.site_description ?? "",
    commissioning_date: initial?.commissioning_date ?? "", monitoring_status: initial?.monitoring_status ?? "planned",
  });
  const [err, setErr] = useState<string | null>(null);
  const num = (v: string) => (v.trim() === "" ? null : Number(v));
  const save = useApiMutation(() => {
    const body: Record<string, unknown> = {
      name: f.name, description: f.description || null, latitude: num(f.latitude), longitude: num(f.longitude),
      site_description: f.site_description || null, commissioning_date: f.commissioning_date || null, monitoring_status: f.monitoring_status,
    };
    if (initial) return api(`/assets/${initial.id}`, { method: "PATCH", json: body });
    return api("/assets", { method: "POST", json: { ...body, id: f.id || null, asset_type: f.asset_type } });
  }, ["assets", "summary"]);
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  return (
    <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); save.mutate(undefined, { onSuccess: onDone, onError: (x) => setErr((x as Error).message) }); }}>
      <div className="grid grid-cols-2 gap-2">
        {!initial && <Field label="Asset ID (optional)"><input className="input" value={f.id} onChange={set("id")} placeholder="auto-generated" /></Field>}
        <Field label="Name"><input className="input" required value={f.name} onChange={set("name")} /></Field>
        {!initial && (
          <Field label="Type">
            <select className="input" value={f.asset_type} onChange={set("asset_type")}>
              {["bridge", "flyover", "dam", "building", "tunnel", "tower", "other"].map((t) => <option key={t} value={t}>{humanize(t)}</option>)}
            </select>
          </Field>
        )}
        <Field label="Monitoring status">
          <select className="input" value={f.monitoring_status} onChange={set("monitoring_status")}>
            {["planned", "active", "paused", "demonstration", "decommissioned"].map((t) => <option key={t} value={t}>{humanize(t)}</option>)}
          </select>
        </Field>
        <Field label="Latitude (WGS84)" hint="Only if known"><input className="input" inputMode="decimal" value={f.latitude} onChange={set("latitude")} /></Field>
        <Field label="Longitude (WGS84)"><input className="input" inputMode="decimal" value={f.longitude} onChange={set("longitude")} /></Field>
        <Field label="Commissioning date"><input type="date" className="input" value={f.commissioning_date} onChange={set("commissioning_date")} /></Field>
      </div>
      <Field label="Description"><textarea className="input h-16" value={f.description} onChange={set("description")} /></Field>
      <Field label="Site description"><textarea className="input h-12" value={f.site_description} onChange={set("site_description")} /></Field>
      {err && <div role="alert" className="text-xs text-red-300">{err}</div>}
      <button className="btn-primary" type="submit" disabled={save.isPending}>{initial ? "Save changes" : "Register asset"}</button>
    </form>
  );
}

function ComponentRegistry({ assetId }: { assetId: string }) {
  const q = useComponents(assetId);
  const [type, setType] = useState("");
  const [text, setText] = useState("");
  const show3d = useShowIn3D();
  const types = useMemo(() => [...new Set((q.data ?? []).map((c) => c.component_type))].sort(), [q.data]);
  const rows = (q.data ?? []).filter((c) => (!type || c.component_type === type) && (!text || `${c.id} ${c.name}`.toLowerCase().includes(text.toLowerCase())));
  return (
    <Card title={`Component registry (${q.data?.length ?? 0})`} actions={
      <>
        <input className="input w-44" placeholder="Search…" value={text} onChange={(e) => setText(e.target.value)} aria-label="Search components" />
        <select className="input w-44" value={type} onChange={(e) => setType(e.target.value)} aria-label="Component type"><option value="">All types</option>{types.map((t) => <option key={t} value={t}>{humanize(t)}</option>)}</select>
      </>
    } bodyClass="max-h-[520px] overflow-auto">
      {q.isLoading ? <Loading /> : q.isError ? <ErrorState error={q.error} /> : !rows.length ? <Empty title="No components">Components are registered with the asset's structural model.</Empty> : (
        <table className="table-base">
          <thead><tr><th>ID</th><th>Name</th><th>Type</th><th>Parent</th><th>Model coords (local m)</th><th>Geo</th><th /></tr></thead>
          <tbody>
            {rows.map((c) => (
              <tr key={c.id} className="row-hover">
                <td className="mono text-accent-soft">{c.id}</td><td>{c.name}</td><td>{humanize(c.component_type)}</td><td className="mono">{c.parent_id ?? "—"}</td>
                <td className="mono">{c.model_x.toFixed(1)}, {c.model_y.toFixed(1)}, {c.model_z.toFixed(1)}</td>
                <td>{c.latitude !== null ? `${c.latitude.toFixed(5)}, ${c.longitude?.toFixed(5)}` : <span className="text-slate-500">—</span>}</td>
                <td><button className="btn-ghost py-0.5" onClick={() => show3d("component", c.id)}>3D</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Card>
  );
}

export default function Assets() {
  const assets = useAssets();
  const assetId = useUI((s) => s.assetId);
  const setAsset = useUI((s) => s.setAsset);
  const [modal, setModal] = useState<"new" | "edit" | null>(null);
  const asset = assets.data?.find((a) => a.id === assetId);
  const summary = useSummary(assetId ?? undefined);
  return (
    <div className="pb-6">
      <PageHeader title="Infrastructure Assets" subtitle="Registered structures, their structural component registry and location information."
        actions={<button className="btn-primary" onClick={() => setModal("new")}><Plus className="h-3.5 w-3.5" />Register asset</button>} />
      <div className="grid gap-3 px-5 lg:grid-cols-[320px_1fr]">
        <Card title="Assets">
          {assets.isLoading ? <Loading /> : assets.isError ? <ErrorState error={assets.error} /> : (
            <ul className="p-2">
              {assets.data!.map((a) => (
                <li key={a.id}>
                  <button onClick={() => setAsset(a.id)} className={`mb-1 w-full rounded-md border p-2 text-left ${a.id === assetId ? "border-accent/50 bg-accent/10" : "border-white/5 hover:bg-white/5"}`}>
                    <div className="flex items-center gap-2"><Building2 className="h-4 w-4 text-accent" /><span className="text-xs font-medium text-white">{a.name}</span></div>
                    <div className="mt-1 flex flex-wrap gap-1"><Chip>{a.asset_type}</Chip><Chip>{humanize(a.monitoring_status)}</Chip>{a.is_demo && <Chip className="border-violet-400/40 text-violet-300">demo</Chip>}</div>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Card>
        {asset && (
          <div className="space-y-3">
            <Card title={asset.name} actions={<button className="btn-ghost" onClick={() => setModal("edit")}>Edit</button>}>
              <div className="grid gap-4 p-3 md:grid-cols-2">
                <div>
                  <KV k="Asset ID" v={asset.id} mono />
                  <KV k="Type" v={humanize(asset.asset_type)} />
                  <KV k="Status" v={humanize(asset.monitoring_status)} />
                  <KV k="Description" v={asset.description} />
                  <KV k="Site" v={asset.site_description} />
                  <KV k="Commissioned" v={asset.commissioning_date ? fmtDate(asset.commissioning_date) : "Unknown"} />
                  <KV k="3D model" v={`${asset.model_kind} · ${asset.model_ref ?? "none"}`} mono />
                  <KV k="Registered" v={fmtDateTime(asset.created_at)} />
                  <KV k="Updated" v={fmtDateTime(asset.updated_at)} />
                </div>
                <div className="space-y-2">
                  <KV k="Latitude/longitude" v={asset.latitude !== null ? `${asset.latitude}, ${asset.longitude}` : "Not recorded"} />
                  <KV k="Model↔world transform" v={asset.geo_transform ? `${(asset.geo_transform as any).calibrated ? "calibrated" : "UNCALIBRATED"} (${(asset.geo_transform as any).method})` : "None — 3D coordinates are local only"} />
                  {summary.data && <KV k="Records" v={`${summary.data.components} components · ${summary.data.inspections} inspections · ${summary.data.open_findings} open findings · ${summary.data.devices_total} devices`} />}
                  <Notice>3D model coordinates are local scene coordinates in metres. They are not latitude/longitude and are only converted when a model-to-world transform is stored (and flagged calibrated or not).</Notice>
                </div>
              </div>
            </Card>
            <Card title="3D structural model"><ModelUpload asset={asset} /></Card>
            <Card title="Map">
              {asset.latitude === null ? (
                <Empty title="No geographic coordinates"><MapPin className="mx-auto mb-1 h-4 w-4" />This asset has no recorded latitude/longitude{asset.is_demo ? " (it is a fictional demonstration bridge)" : ""}. Edit the asset to add surveyed coordinates.</Empty>
              ) : !TILE_URL ? (
                <Empty title="Map source not configured">Coordinates: {asset.latitude}, {asset.longitude}. Set <code className="mono">VITE_MAP_TILE_URL</code> (e.g. an OpenStreetMap-compatible tile server you are permitted to use) to enable the interactive map.</Empty>
              ) : (
                <Suspense fallback={<Loading />}><AssetMap assets={assets.data ?? []} selected={asset.id} tileUrl={TILE_URL} /></Suspense>
              )}
            </Card>
            <ComponentRegistry assetId={asset.id} />
          </div>
        )}
      </div>
      {modal && (
        <Modal title={modal === "new" ? "Register infrastructure asset" : `Edit ${asset?.name}`} onClose={() => setModal(null)}>
          <AssetForm initial={modal === "edit" ? asset : undefined} onDone={() => setModal(null)} />
        </Modal>
      )}
    </div>
  );
}
