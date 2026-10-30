import { CartesianGrid, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Scatter, ComposedChart, Tooltip, XAxis, YAxis } from "recharts";
import { useBaselines, useFeatures, useReadings, useSystemStatus } from "@/api/hooks";
import type { Device } from "@/api/types";
import { fmtAgo, fmtTime } from "@/lib/format";
import { Empty, ErrorState, Loading, Notice, SourceBadge } from "./ui";

const axisProps = { stroke: "#475569", fontSize: 10, tickLine: false } as const;
const tooltipStyle = { contentStyle: { background: "#060b16", border: "1px solid rgba(34,211,238,.3)", fontSize: 11 }, labelStyle: { color: "#94a3b8" } };

/** Which single source to plot for a device under the global data-source mode ("__hidden__" if excluded).
 * Series are never merged: in "all" mode each device shows its own native source (real or simulated);
 * uploaded history is viewed with the "Uploaded" mode. */
export function displaySource(device: Device, mode: string | undefined): string {
  if (!mode || mode === "all") return device.data_source === "simulated" ? "simulated" : "real";
  if (device.data_source === "simulated") return mode === "simulated" ? "simulated" : "__hidden__";
  return mode === "simulated" ? "__hidden__" : mode; // real device: real or uploaded
}

export function SourceGate({ device, children }: { device: Device; children: (source: string | undefined) => JSX.Element }) {
  const status = useSystemStatus();
  const mode = status.data?.data_source.mode;
  const src = displaySource(device, mode);
  if (src === "__hidden__")
    return (
      <Notice>
        This device's {device.data_source === "simulated" ? "simulated" : "real/uploaded"} data is hidden by the current data-source mode (<b>{mode}</b>).
        Change the mode in the top bar to view it.
      </Notice>
    );
  return children(src);
}

export function ReadingsChart({ device, source, height = 160, live = true }: { device: Device; source?: string; height?: number; live?: boolean }) {
  const q = useReadings(device.id, source, 300, live);
  if (q.isLoading) return <Loading label="Loading readings…" />;
  if (q.isError) return <ErrorState error={q.error} />;
  const rows = q.data ?? [];
  if (!rows.length) return <Empty title="No readings recorded">{device.data_source === "real" ? "No data has been received from this device." : "No simulated data generated yet."}</Empty>;
  const sources = [...new Set(rows.map((r) => r.source))];
  const last = rows[rows.length - 1];
  const data = rows.map((r) => ({ t: new Date(r.ts).getTime(), ax: r.ax, ay: r.ay, az: r.az }));
  return (
    <div>
      <div className="mb-1 flex items-center justify-between text-[10px] text-slate-400">
        <span>Raw acceleration (g), last {rows.length} samples · latest {fmtAgo(last.ts)}</span>
        <span className="flex gap-1">{sources.map((s) => <SourceBadge key={s} source={s} />)}</span>
      </div>
      <ResponsiveContainer width="100%" height={height}>
        <LineChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: -12 }}>
          <CartesianGrid stroke="#1e293b" strokeDasharray="2 4" />
          <XAxis dataKey="t" type="number" domain={["dataMin", "dataMax"]} tickFormatter={(t) => fmtTime(new Date(t).toISOString())} {...axisProps} />
          <YAxis yAxisId="z" domain={["auto", "auto"]} {...axisProps} tickFormatter={(v) => v.toFixed(3)} />
          <YAxis yAxisId="xy" orientation="right" domain={["auto", "auto"]} {...axisProps} tickFormatter={(v) => v.toFixed(3)} />
          <Tooltip {...tooltipStyle} labelFormatter={(t) => fmtTime(new Date(t as number).toISOString())} formatter={(v: number) => v.toFixed(4)} />
          <Legend wrapperStyle={{ fontSize: 10 }} />
          <Line yAxisId="z" dataKey="az" stroke="#22d3ee" dot={false} strokeWidth={1.2} isAnimationActive={false} />
          <Line yAxisId="xy" dataKey="ax" stroke="#a78bfa" dot={false} strokeWidth={1} isAnimationActive={false} />
          <Line yAxisId="xy" dataKey="ay" stroke="#f472b6" dot={false} strokeWidth={1} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

export function FeaturesChart({ device, source, height = 170, limit = 240 }: { device: Device; source?: string; height?: number; limit?: number }) {
  const q = useFeatures(device.id, source, limit);
  const b = useBaselines(device.id);
  if (q.isLoading) return <Loading label="Loading features…" />;
  if (q.isError) return <ErrorState error={q.error} />;
  const feats = q.data ?? [];
  if (!feats.length) return <Empty title="No vibration features">Features are computed per {60} s window once readings exist.</Empty>;
  const srcs = [...new Set(feats.map((f) => f.source))];
  const active = (b.data ?? []).find((x) => x.active && srcs.includes(x.source));
  const data = feats.map((f) => ({ t: new Date(f.window_start).getTime(), rms: f.rms_dyn, peak: f.peak_dyn, anomaly: f.anomaly ? f.rms_dyn : null, incomplete: f.data_quality !== "ok" }));
  const nAnom = feats.filter((f) => f.anomaly).length;
  const nInc = feats.filter((f) => f.data_quality !== "ok").length;
  return (
    <div>
      <div className="mb-1 flex flex-wrap items-center justify-between gap-1 text-[10px] text-slate-400">
        <span>rms_dyn / peak_dyn (g) per {feats[0].window_s}s window · {nAnom} anomalous · {nInc} incomplete</span>
        <span className="flex gap-1">{srcs.map((s) => <SourceBadge key={s} source={s} />)}</span>
      </div>
      <ResponsiveContainer width="100%" height={height}>
        <ComposedChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: -12 }}>
          <CartesianGrid stroke="#1e293b" strokeDasharray="2 4" />
          <XAxis dataKey="t" type="number" domain={["dataMin", "dataMax"]} tickFormatter={(t) => fmtTime(new Date(t).toISOString())} {...axisProps} />
          <YAxis {...axisProps} tickFormatter={(v) => v.toFixed(3)} />
          <Tooltip {...tooltipStyle} labelFormatter={(t) => fmtTime(new Date(t as number).toISOString())} formatter={(v: number) => (v === null ? "—" : v.toFixed(4))} />
          <Legend wrapperStyle={{ fontSize: 10 }} />
          <Line dataKey="rms" name="rms_dyn" stroke="#22d3ee" dot={false} strokeWidth={1.4} isAnimationActive={false} />
          <Line dataKey="peak" name="peak_dyn" stroke="#64748b" dot={false} strokeWidth={1} isAnimationActive={false} />
          <Scatter dataKey="anomaly" name="anomaly" fill="#ef4444" isAnimationActive={false} />
          {active && <ReferenceLine y={active.rms_dyn_mean} stroke="#a3e635" strokeDasharray="4 3" label={{ value: `baseline v${active.version}`, fill: "#a3e635", fontSize: 9, position: "insideTopLeft" }} />}
          {active && feats[feats.length - 1].thresholds?.rms_dyn_limit && (
            <ReferenceLine y={feats[feats.length - 1].thresholds!.rms_dyn_limit} stroke="#ef4444" strokeDasharray="2 3" label={{ value: "anomaly limit", fill: "#ef4444", fontSize: 9, position: "insideTopRight" }} />
          )}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
