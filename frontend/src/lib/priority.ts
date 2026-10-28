import type { Priority } from "@/api/types";

export const PRIORITIES: Priority[] = ["critical", "high", "medium", "low", "unassessed"];

/** Colours express configured review priority, never certified structural safety. */
export const PRIORITY_COLOR: Record<Priority, string> = {
  critical: "#ef4444",
  high: "#f43f5e",
  medium: "#fb923c",
  low: "#facc15",
  unassessed: "#94a3b8",
};
export const PRIORITY_LABEL: Record<Priority, string> = {
  critical: "Critical review",
  high: "High",
  medium: "Medium",
  low: "Low",
  unassessed: "Unassessed",
};
export const priorityRank = (p: string) => Math.max(0, ["unassessed", "low", "medium", "high", "critical"].indexOf(p));

export const CATEGORIES = [
  "suspected_crack", "suspected_corrosion", "exposed_reinforcement", "vibration_anomaly", "surface_deformation", "other", "unclassified",
];
export const REVIEW_STATUSES = ["new", "under_review", "confirmed", "monitoring", "false_positive", "repaired", "closed"];

export const CONNECTION_COLOR: Record<string, string> = {
  online: "#34d399",
  stale: "#facc15",
  offline: "#64748b",
  never_connected: "#64748b",
  simulated: "#22d3ee",
  simulated_idle: "#64748b",
  maintenance: "#a78bfa",
  decommissioned: "#475569",
};

export const SOURCE_STYLE: Record<string, { label: string; cls: string }> = {
  real: { label: "Real", cls: "border-emerald-400/40 text-emerald-300 bg-emerald-400/10" },
  uploaded: { label: "Uploaded", cls: "border-sky-400/40 text-sky-300 bg-sky-400/10" },
  simulated: { label: "Simulated", cls: "border-fuchsia-400/40 text-fuchsia-300 bg-fuchsia-400/10" },
  demo: { label: "Demo", cls: "border-violet-400/40 text-violet-300 bg-violet-400/10" },
};
