import { useQuery } from "@tanstack/react-query";
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, qs } from "@/api/client";
import type { Device, EnvSeries } from "@/api/types";
import { fmtAgo, fmtDateTime, fmtNum, fmtTime } from "@/lib/format";
import { Empty, ErrorState, Loading, SourceBadge, Stat } from "./ui";

const axis = { stroke: "#475569", fontSize: 10, tickLine: false } as const;

/** Temperature / humidity / dew point. Exposure context only — not crack detection. */
export function EnvironmentChart({ device, source, height = 170, bucket = 0 }: { device: Device; source?: string; height?: number; bucket?: number }) {
  const q = useQuery({
    queryKey: ["environment", device.id, source, bucket],
    queryFn: () => api<EnvSeries>(`/sensors/${device.id}/environment${qs({ source, bucket_s: bucket, limit: bucket ? 50000 : 720 })}`),
    refetchInterval: 15_000,
  });
  if (q.isLoading) return <Loading label="Loading temperature/humidity…" />;
  if (q.isError) return <ErrorState error={q.error} />;
  const d = q.data!;
  if (!d.latest) return <Empty title="No temperature/humidity readings">Readings appear when the node publishes to <code className="mono">bridge/{device.id}/env</code>.</Empty>;
  const l = d.latest;
  const data = d.series.map((p) => ({ t: new Date(p.t).getTime(), temp: p.temp_mean, rh: p.rh_mean, dew: p.dew_point_mean }));
  return (
    <div className="space-y-2">
      <div className="grid grid-cols-4 gap-2">
        <Stat label="Temperature" value={l.temperature_c !== null ? `${fmtNum(l.temperature_c, 1)} °C` : "—"} />
        <Stat label="Humidity" value={l.humidity_pct !== null ? `${fmtNum(l.humidity_pct, 0)} %` : "—"} />
        <Stat label="Dew point" value={l.dew_point_c !== null ? `${fmtNum(l.dew_point_c, 1)} °C` : "—"} hint="Magnus approximation" />
        <Stat label="Latest" value={fmtAgo(l.ts)} hint={fmtDateTime(l.ts)} tone={l.age_s > 300 ? "warn" : undefined} />
      </div>
      <div className="flex items-center justify-between text-[10px] text-slate-400">
        <span>{l.sensor_model ?? "sensor"} · {d.series.length} {bucket ? "buckets" : "samples"}</span><SourceBadge source={l.source} />
      </div>
      <ResponsiveContainer width="100%" height={height}>
        <LineChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: -12 }}>
          <CartesianGrid stroke="#1e293b" strokeDasharray="2 4" />
          <XAxis dataKey="t" type="number" domain={["dataMin", "dataMax"]} tickFormatter={(t) => (bucket >= 3600 ? fmtDateTime : fmtTime)(new Date(t).toISOString())} {...axis} />
          <YAxis yAxisId="c" {...axis} unit="°" />
          <YAxis yAxisId="rh" orientation="right" domain={[0, 100]} {...axis} unit="%" />
          <Tooltip contentStyle={{ background: "#060b16", border: "1px solid rgba(34,211,238,.3)", fontSize: 11 }} labelFormatter={(t) => fmtDateTime(new Date(t as number).toISOString())}
            formatter={(v: number) => (v === null ? "—" : v.toFixed(1))} />
          <Legend wrapperStyle={{ fontSize: 10 }} />
          <Line yAxisId="c" dataKey="temp" name="temperature °C" stroke="#fb923c" dot={false} isAnimationActive={false} />
          <Line yAxisId="c" dataKey="dew" name="dew point °C" stroke="#a78bfa" dot={false} strokeDasharray="4 3" isAnimationActive={false} />
          <Line yAxisId="rh" dataKey="rh" name="humidity %" stroke="#38bdf8" dot={false} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
      <p className="text-[10px] text-slate-500">{d.note}</p>
    </div>
  );
}
