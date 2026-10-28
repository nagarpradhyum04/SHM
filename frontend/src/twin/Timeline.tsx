import clsx from "clsx";
import { useMemo, useState } from "react";
import { useEvents } from "@/api/hooks";
import type { EventLog } from "@/api/types";
import { Segmented } from "@/components/ui";
import { fmtDateTime, isoDaysAgo } from "@/lib/format";
import { PRIORITY_COLOR } from "@/lib/priority";
import { useUI } from "@/store/ui";

const TYPE_STYLE: Record<string, { color: string; label: string; row: number }> = {
  inspection: { color: "#38bdf8", label: "Inspections", row: 0 },
  defect_recorded: { color: "#fb923c", label: "Defect discoveries", row: 1 },
  defect_status: { color: "#fdba74", label: "Defect discoveries", row: 1 },
  sensor_anomaly: { color: "#e879f9", label: "Sensor anomalies", row: 2 },
  alert_raised: { color: "#ef4444", label: "Alerts", row: 3 },
  alert_acknowledged: { color: "#facc15", label: "Alerts", row: 3 },
  alert_resolved: { color: "#34d399", label: "Alerts", row: 3 },
  alert_reopened: { color: "#ef4444", label: "Alerts", row: 3 },
};
const ROWS = ["Inspections", "Defect discoveries", "Sensor anomalies", "Alerts"];

export function Timeline({ assetId }: { assetId: string }) {
  const [days, setDays] = useState<"1" | "7" | "30" | "120">("120");
  const start = useMemo(() => isoDaysAgo(+days), [days]);
  const q = useEvents({ asset_id: assetId, start, limit: 1000, event_type: Object.keys(TYPE_STYLE) });
  const select = useUI((s) => s.select);
  const [hover, setHover] = useState<EventLog | null>(null);
  const t0 = new Date(start).getTime();
  const t1 = Date.now();
  const events = q.data ?? [];

  const onClick = (e: EventLog) => {
    if (e.ref_type === "defect" && e.ref_id) select({ kind: "defect", id: e.ref_id });
    else if (e.component_id) select({ kind: "component", id: e.component_id });
    else if (e.device_id) select({ kind: "device", id: e.device_id });
  };

  return (
    <div className="flex h-full flex-col px-3 py-2">
      <div className="mb-1 flex items-center justify-between">
        <div className="panel-title">Timeline</div>
        <div className="flex items-center gap-3">
          <span className="text-[10px] text-slate-500">{hover ? `${fmtDateTime(hover.ts)} — ${hover.title}` : `${events.length} events`}</span>
          <Segmented size="xs" value={days} onChange={setDays} options={[{ value: "1", label: "24h" }, { value: "7", label: "7d" }, { value: "30", label: "30d" }, { value: "120", label: "120d" }]} />
        </div>
      </div>
      <div className="relative min-h-0 flex-1">
        {ROWS.map((r, i) => (
          <div key={r} className="absolute left-0 right-0 flex items-center" style={{ top: `${i * 25}%`, height: "25%" }}>
            <span className="w-28 shrink-0 text-[10px] text-slate-500">{r}</span>
            <div className="relative h-px flex-1 bg-white/10" />
          </div>
        ))}
        <div className="absolute bottom-0 left-28 right-0 top-0">
          {events.map((e) => {
            const st = TYPE_STYLE[e.event_type];
            if (!st) return null;
            const x = ((new Date(e.ts).getTime() - t0) / (t1 - t0)) * 100;
            if (x < 0 || x > 100) return null;
            const color = e.priority && e.event_type === "alert_raised" ? PRIORITY_COLOR[e.priority] : st.color;
            return (
              <button key={e.id} aria-label={`${e.title} at ${fmtDateTime(e.ts)}`}
                className={clsx("absolute h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full border border-black/40 hover:scale-150", e.data_source === "simulated" || e.data_source === "demo" ? "opacity-80" : "")}
                style={{ left: `${x}%`, top: `${st.row * 25 + 12.5}%`, background: color }}
                onMouseEnter={() => setHover(e)} onMouseLeave={() => setHover(null)} onClick={() => onClick(e)} />
            );
          })}
        </div>
      </div>
      <div className="ml-28 flex justify-between text-[9px] text-slate-600">
        <span>{fmtDateTime(start)}</span><span>now</span>
      </div>
    </div>
  );
}
