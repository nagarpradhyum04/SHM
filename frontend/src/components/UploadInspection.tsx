import { ImagePlus, Sparkles } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api, API_BASE } from "@/api/client";
import { useComponents, useDevices, useSystemStatus } from "@/api/hooks";
import type { Defect, ImageRec, Inspection } from "@/api/types";
import { useQueryClient } from "@tanstack/react-query";
import { humanize } from "@/lib/format";
import { EvidenceImage } from "./DefectEvidence";
import { Field, Notice, PriorityBadge } from "./ui";

export interface InspectionResult { inspection: Inspection; image: ImageRec | null; defects: Defect[] }

const DEMO_VARIANTS = ["crack", "corrosion", "exposed_rebar", "clean", "blurry"];
const ACCEPT = "image/jpeg,image/png,image/bmp,image/webp";

export function UploadInspection({ assetId, defaultComponent, onResult }: { assetId: string; defaultComponent?: string; onResult?: (r: InspectionResult) => void }) {
  const comps = useComponents(assetId);
  const devices = useDevices(assetId);
  const status = useSystemStatus();
  const qc = useQueryClient();
  const [component, setComponent] = useState(defaultComponent ?? "");
  const [camera, setCamera] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [demo, setDemo] = useState("crack");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<InspectionResult | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const maxMb = status.data?.max_upload_mb ?? 15;

  useEffect(() => setComponent(defaultComponent ?? ""), [defaultComponent]);
  useEffect(() => {
    if (!file) return setPreview(null);
    const u = URL.createObjectURL(file);
    setPreview(u);
    return () => URL.revokeObjectURL(u);
  }, [file]);

  const choose = (f: File | null) => {
    setError(null);
    setResult(null);
    if (!f) return setFile(null);
    if (!ACCEPT.split(",").includes(f.type)) return setError(`Unsupported file type ${f.type || "(unknown)"}. Use JPEG, PNG, BMP or WebP.`);
    if (f.size > maxMb * 1024 * 1024) return setError(`File is larger than the ${maxMb} MB limit.`);
    setFile(f);
  };

  const finish = (r: InspectionResult) => {
    setResult(r);
    onResult?.(r);
    ["inspections", "defects", "summary", "events", "alerts", "component"].forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
  };

  const submit = async () => {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("asset_id", assetId);
      if (component) fd.append("component_id", component);
      if (camera) fd.append("device_id", camera);
      const actor = localStorage.getItem("ss.actor");
      if (actor) fd.append("performed_by", actor);
      const res = await fetch(`${API_BASE}/inspections/image`, { method: "POST", body: fd });
      const body = await res.json().catch(() => null);
      if (!res.ok) throw new Error(typeof body?.detail === "string" ? body.detail : `Upload failed (${res.status})`);
      finish(body);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const runDemo = async () => {
    setBusy(true);
    setError(null);
    try {
      finish(await api<InspectionResult>("/inspections/demo", { method: "POST", json: { asset_id: assetId, component_id: component || null, variant: demo, seed: Math.floor(Math.random() * 1000) } }));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const geomComps = (comps.data ?? []).filter((c) => c.geometry?.type !== "group");
  const modelAvailable = status.data?.models.available;

  return (
    <div className="space-y-3">
      {status.isSuccess && !modelAvailable && (
        <Notice tone="warn"><b>No trained inference model is installed.</b> Images are validated, stored and recorded as inspections with status
          “model unavailable”; no prediction is generated. You can record findings manually. See <code className="mono">backend/ml/README.md</code>.</Notice>
      )}
      {modelAvailable && <Notice>Active model(s): {status.data!.models.loaded.map((m) => `${m.id} v${m.version} (${m.categories.join(", ")})`).join("; ")}</Notice>}
      <div className="grid grid-cols-2 gap-2">
        <Field label="Component">
          <select className="input" value={component} onChange={(e) => setComponent(e.target.value)} aria-label="Component">
            <option value="">Unassigned</option>
            {geomComps.map((c) => <option key={c.id} value={c.id}>{c.name} ({c.id})</option>)}
          </select>
        </Field>
        <Field label="Camera (optional)">
          <select className="input" value={camera} onChange={(e) => setCamera(e.target.value)} aria-label="Camera">
            <option value="">None / handheld</option>
            {(devices.data ?? []).filter((d) => d.device_type === "camera").map((d) => <option key={d.id} value={d.id}>{d.id}</option>)}
          </select>
        </Field>
      </div>
      <div
        className="flex cursor-pointer flex-col items-center justify-center gap-1 rounded-lg border border-dashed border-accent/30 bg-accent/[0.03] p-4 text-center text-xs text-slate-400 hover:bg-accent/[0.06]"
        onClick={() => inputRef.current?.click()}
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => { e.preventDefault(); choose(e.dataTransfer.files[0] ?? null); }}
        role="button" tabIndex={0} aria-label="Choose image file"
      >
        <ImagePlus className="h-5 w-5 text-accent" />
        {file ? <span className="text-slate-200">{file.name} · {(file.size / 1024).toFixed(0)} KB</span> : <span>Drop an inspection image or click to choose (JPEG/PNG/BMP/WebP, ≤ {maxMb} MB)</span>}
        <input ref={inputRef} type="file" accept={ACCEPT} className="hidden" onChange={(e) => choose(e.target.files?.[0] ?? null)} data-testid="file-input" />
      </div>
      {preview && <img src={preview} alt="Preview" className="max-h-48 rounded border border-white/10" />}
      <div className="flex flex-wrap items-center gap-2">
        <button className="btn-primary" disabled={!file || busy} onClick={submit}>{busy ? "Processing…" : "Upload & inspect"}</button>
        <span className="text-[11px] text-slate-500">or</span>
        <select className="input w-40" value={demo} onChange={(e) => setDemo(e.target.value)} aria-label="Demo image">
          {DEMO_VARIANTS.map((v) => <option key={v} value={v}>Synthetic: {humanize(v)}</option>)}
        </select>
        <button className="btn-ghost" disabled={busy} onClick={runDemo} title="Runs the normal pipeline on a watermarked synthetic image labelled as demo data"><Sparkles className="h-3.5 w-3.5" />Use demo image</button>
      </div>
      {error && <div role="alert" className="rounded border border-red-400/30 bg-red-500/10 p-2 text-xs text-red-200">{error}</div>}
      {result && (
        <div className="space-y-2 rounded-lg border border-white/10 p-3">
          <div className="flex items-center justify-between">
            <div className="text-xs font-medium text-white">Inspection {result.inspection.id}</div>
            <span className="chip border-white/15 text-slate-300">{humanize(result.inspection.status)}</span>
          </div>
          {result.image && <EvidenceImage image={result.image} className="max-w-xs" />}
          {result.inspection.status === "model_unavailable" && <div className="text-[11px] text-amber-200">Stored without AI analysis (no model installed). Record findings manually if present.</div>}
          {result.inspection.status === "completed" && (
            <div className="text-[11px] text-slate-300">
              Model {result.inspection.model_id} v{result.inspection.model_version} · {result.inspection.inference_ms?.toFixed(1)} ms ·
              probabilities {JSON.stringify(result.inspection.inference_output?.raw?.probabilities)}
            </div>
          )}
          {result.defects.map((d) => <div key={d.id} className="flex items-center gap-2 text-xs">AI finding <span className="mono">{d.id}</span> {humanize(d.category)} <PriorityBadge p={d.priority} /></div>)}
          {result.image && !result.image.quality?.ok && <div className="text-[11px] text-amber-200">Image-quality issues: {result.image.quality?.issues.join(", ")}</div>}
        </div>
      )}
    </div>
  );
}
