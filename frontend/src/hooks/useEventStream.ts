import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { API_BASE } from "@/api/client";

const TOPIC_KEYS: Record<string, string[]> = {
  alerts: ["alerts", "alert", "summary", "events"],
  defects: ["defects", "defect", "component", "summary", "events"],
  inspections: ["inspections", "summary", "events", "component"],
  readings: ["readings", "devices"],
  features: ["features", "vibration-history"],
  devices: ["devices", "summary"],
};

/** Subscribes to backend server-sent events and invalidates affected queries. Returns connection state. */
export function useEventStream(): "connecting" | "open" | "error" {
  const qc = useQueryClient();
  const [state, setState] = useState<"connecting" | "open" | "error">("connecting");
  useEffect(() => {
    if (typeof EventSource === "undefined") return;
    const es = new EventSource(`${API_BASE}/stream`);
    const pending = new Set<string>();
    let timer: ReturnType<typeof setTimeout> | null = null;
    es.onopen = () => setState("open");
    es.onerror = () => setState("error");
    es.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data);
        (TOPIC_KEYS[msg.topic] ?? []).forEach((k) => pending.add(k));
        if (!timer)
          timer = setTimeout(() => {
            pending.forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
            pending.clear();
            timer = null;
          }, 800);
      } catch {
        /* ignore malformed messages */
      }
    };
    return () => {
      es.close();
      if (timer) clearTimeout(timer);
    };
  }, [qc]);
  return state;
}
