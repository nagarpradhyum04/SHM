import { useQuery } from "@tanstack/react-query";
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, qs } from "@/api/client";
import type { Device, SummaryPoint } from "@/api/types";
import { fmtAgo, fmtNum, fmtTime } from "@/lib/format";
import { Chip, Empty, ErrorState, Loading, SourceBadge, Stat } from "./ui";

const axis = { stroke: "#475569", fontSize: 10, tickLine: false } as const;
const LEVEL_CLS: Record<string, string> = {
  CALM: "border-emerald-400/40 text-emerald-300", LOW: "border-sky-400/40 text-sky-300", MODERATE: "border-amber-400/40 text-amber-300",
  HIGH: "border-orange-400/40 text-orange-300", SEVERE: "border-red-400/40 text-red-300",
};

export function useSummaries(device: Device, source?: string, limit = 240) {
  return useQuery({
    queryKey: ["summaries", device.id, source, limit],
    queryFn: () => api<SummaryPoint[]>(`/sensors/${device.id}/summaries${qs({ source, limit })}`),
    refetchInterval: 3_000,
  });
}

/** Live view of the vibration summaries computed on the ESP32 (RMS/peak of dynamic acceleration, tilt). */
export function SummaryChart({ device, source, height = 190, hideWhenEmpty }: { device: Device; source?: string; height?: number; hideWhenEmpty?: boolean }) {
  const q = useSummaries(device, source);
  if (q.isLoading) return <Loading label="Loading live vibration…" />;
  if (q.isError) return <ErrorState error={q.error} />;
  const rows = q.data ?? [];
  if (!rows.length && hideWhenEmpty) return null;
  if (!rows.length) return <Empty title="No vibration summaries yet">They appear as soon as the node publishes (every 0.5 s).</Empty>;
  const last = rows[rows.length - 1];
  const data = rows.map((r) => ({ t: new Date(r.ts).getTime(), vib: r.vib_rms_g, peak: r.peak_g, tilt: r.tilt_deg }));
  return (
    <div className="space-y-2">
      <div className="grid grid-cols-4 gap-2">
        <Stat label="Vibration RMS" value={`${fmtNum(last.vib_rms_g, 4)} g`} />
        <Stat label="Peak" value={`${fmtNum(last.peak_g, 4)} g`} />
        <Stat label="Tilt" value={`${fmtNum(last.tilt_deg, 2)}°`} />
        <Stat label="Latest" value={fmtAgo(last.ts)} />
      </div>
      <div className="flex flex-wrap items-center justify-between gap-1 text-[10px] text-slate-400">
        <span className="flex items-center gap-1.5">Device level {last.device_level ? <Chip className={LEVEL_CLS[last.device_level] ?? ""}>{last.device_level}</Chip> : "—"}
          <span title="Thresholds chosen in the firmware, not engineering limits">(firmware's own label)</span>
          {last.mpu_ok === false && <Chip className="border-red-400/40 text-red-300">MPU fault</Chip>}
          {last.dht_ok === false && <Chip className="border-amber-400/40 text-amber-300">DHT fault</Chip>}
          {last.time_source === "server" && <span title="The node sends no clock; arrival time is used">· server time</span>}
        </span>
        <SourceBadge source={last.source} />
      </div>
      <ResponsiveContainer width="100%" height={height}>
        <LineChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: -12 }}>
          <CartesianGrid stroke="#1e293b" strokeDasharray="2 4" />
          <XAxis dataKey="t" type="number" domain={["dataMin", "dataMax"]} tickFormatter={(t) => fmtTime(new Date(t).toISOString())} {...axis} />
          <YAxis yAxisId="g" {...axis} tickFormatter={(v) => v.toFixed(3)} />
          <YAxis yAxisId="deg" orientation="right" domain={["auto", "auto"]} {...axis} unit="°" />
          <Tooltip contentStyle={{ background: "#060b16", border: "1px solid rgba(34,211,238,.3)", fontSize: 11 }}
            labelFormatter={(t) => fmtTime(new Date(t as number).toISOString())} formatter={(v: number) => (v === null ? "—" : v.toFixed(4))} />
          <Legend wrapperStyle={{ fontSize: 10 }} />
          <Line yAxisId="g" dataKey="vib" name="vibration RMS (g)" stroke="#22d3ee" dot={false} isAnimationActive={false} />
          <Line yAxisId="g" dataKey="peak" name="peak (g)" stroke="#64748b" dot={false} isAnimationActive={false} />
          <Line yAxisId="deg" dataKey="tilt" name="tilt (°)" stroke="#a78bfa" dot={false} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
