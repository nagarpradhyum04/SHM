import { Box, Trash2, Upload } from "lucide-react";
import { useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api, API_BASE } from "@/api/client";
import type { Asset } from "@/api/types";
import { Link } from "react-router-dom";
import { fmtBytes, fmtDateTime } from "@/lib/format";
import { KV, Notice } from "./ui";

/** Upload a self-contained GLB of the structure; optionally register its nodes as components. */
export function ModelUpload({ asset }: { asset: Asset }) {
  const qc = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const [register, setRegister] = useState(true);
  const [prefix, setPrefix] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const meta = asset.model_meta;

  const refresh = () => ["assets", "components", "summary"].forEach((k) => qc.invalidateQueries({ queryKey: [k] }));

  const upload = async (file: File) => {
    setMsg(null);
    if (!file.name.toLowerCase().endsWith(".glb")) return setMsg({ ok: false, text: "Please choose a binary glTF (.glb) file." });
    setBusy(true);
    const fd = new FormData();
    fd.append("file", file);
    fd.append("register_components", String(register));
    fd.append("id_prefix", prefix);
    try {
      const r = await fetch(`${API_BASE}/assets/${asset.id}/model`, { method: "POST", body: fd });
      const b = await r.json().catch(() => null);
      if (!r.ok) throw new Error(typeof b?.detail === "string" ? b.detail : `Upload failed (${r.status})`);
      setMsg({ ok: true, text: `Model stored · ${b.model_meta.mesh_nodes} mesh nodes · components created ${b.components_created}, updated ${b.components_updated}, no longer present ${b.components_retired}.` });
      refresh();
    } catch (e) {
      setMsg({ ok: false, text: (e as Error).message });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-3 p-3">
      {asset.model_kind === "gltf" && meta ? (
        <div>
          <KV k="File" v={`${meta.filename ?? "model.glb"} · ${fmtBytes(meta.size_bytes)}`} />
          <KV k="Uploaded" v={fmtDateTime(meta.uploaded_at)} />
          <KV k="Nodes" v={`${meta.nodes} (${meta.mesh_nodes} with meshes)`} />
          <KV k="Bounds (model m)" v={meta.bounds ? `${meta.bounds.min.map((v) => v.toFixed(1)).join(", ")} → ${meta.bounds.max.map((v) => v.toFixed(1)).join(", ")}` : "—"} mono />
          <KV k="Convention" v={meta.convention} />
        </div>
      ) : (
        <p className="text-xs text-slate-400">Currently using: <b>{asset.model_kind === "procedural" ? "procedural demonstration model" : "no 3D model"}</b>.</p>
      )}
      <div className="flex flex-wrap items-center gap-3 text-xs">
        <label className="flex items-center gap-1.5"><input type="checkbox" checked={register} onChange={(e) => setRegister(e.target.checked)} />Register model parts as components</label>
        <input className="input w-40" placeholder="Component ID prefix (optional)" value={prefix} onChange={(e) => setPrefix(e.target.value)} aria-label="Component ID prefix" />
      </div>
      <div className="flex flex-wrap gap-2">
        <button className="btn-primary" disabled={busy} onClick={() => input.current?.click()}><Upload className="h-3.5 w-3.5" />{busy ? "Uploading…" : asset.model_kind === "gltf" ? "Upload revised model" : "Upload 3D model (.glb)"}</button>
        {asset.model_kind === "gltf" && <Link className="btn-ghost" to="/twin"><Box className="h-3.5 w-3.5" />View in Digital Twin</Link>}
        {asset.model_kind === "gltf" && (
          <button className="btn-danger" onClick={async () => { await api(`/assets/${asset.id}/model`, { method: "DELETE" }); refresh(); }}><Trash2 className="h-3.5 w-3.5" />Stop using uploaded model</button>
        )}
        <input ref={input} type="file" accept=".glb,model/gltf-binary" className="hidden" data-testid="model-input" onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
      </div>
      {msg && <div role={msg.ok ? "status" : "alert"} className={`text-xs ${msg.ok ? "text-emerald-300" : "text-red-300"}`}>{msg.text}</div>}
      <Notice>Export a single self-contained <b>.glb</b> (glTF 2.0, Y-up, metres; no Draco/meshopt compression). Name the parts in your modelling tool
        (e.g. "Pier 2 column", "Deck span 3"): each named part becomes a selectable component. Re-uploading a revised model keeps component IDs
        for parts with the same name, so findings and devices stay attached. Then place devices from the Digital Twin (select a part → Add device here → Edit placement).</Notice>
    </div>
  );
}
