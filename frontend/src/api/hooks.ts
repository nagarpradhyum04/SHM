import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, qs } from "./client";
import type {
  Alert, AlertDetail, AlertRule, Asset, Baseline, Component, ComponentDetail, Defect, DefectDetail, Device, EventLog,
  Feature, Inspection, ModelRec, Reading, Report, RULResult, Summary, SystemStatus,
} from "./types";

export const keys = {
  assets: ["assets"] as const,
  summary: (a: string) => ["summary", a] as const,
  components: (a: string) => ["components", a] as const,
  component: (id: string) => ["component", id] as const,
  devices: (a: string) => ["devices", a] as const,
  defects: (p: object) => ["defects", p] as const,
  defect: (id: string) => ["defect", id] as const,
  alerts: (p: object) => ["alerts", p] as const,
  alert: (id: string) => ["alert", id] as const,
  events: (p: object) => ["events", p] as const,
  inspections: (p: object) => ["inspections", p] as const,
  status: ["system-status"] as const,
  settings: ["settings"] as const,
};

export const useAssets = () => useQuery({ queryKey: keys.assets, queryFn: () => api<Asset[]>("/assets") });
export const useSummary = (assetId?: string) =>
  useQuery({ queryKey: keys.summary(assetId ?? ""), queryFn: () => api<Summary>(`/assets/${assetId}/summary`), enabled: !!assetId });
export const useComponents = (assetId?: string) =>
  useQuery({ queryKey: keys.components(assetId ?? ""), queryFn: () => api<Component[]>(`/assets/${assetId}/components`), enabled: !!assetId, staleTime: 5 * 60_000 });
export const useComponentDetail = (id?: string | null) =>
  useQuery({ queryKey: keys.component(id ?? ""), queryFn: () => api<ComponentDetail>(`/components/${id}`), enabled: !!id });
export const useDevices = (assetId?: string) =>
  useQuery({ queryKey: keys.devices(assetId ?? ""), queryFn: () => api<Device[]>(`/devices${qs({ asset_id: assetId })}`), enabled: !!assetId, refetchInterval: 15_000 });

export interface DefectQuery {
  asset_id?: string; priority?: string[]; category?: string[]; review_status?: string[]; component_id?: string[];
  detection_source?: string[]; data_source?: string[]; start?: string; end?: string; sort?: string;
}
export const useDefects = (p: DefectQuery, enabled = true) =>
  useQuery({ queryKey: keys.defects(p), queryFn: () => api<Defect[]>(`/defects${qs(p as any)}`), enabled });
export const useDefectDetail = (id?: string | null) =>
  useQuery({ queryKey: keys.defect(id ?? ""), queryFn: () => api<DefectDetail>(`/defects/${id}`), enabled: !!id });

export interface AlertQuery { asset_id?: string; status?: string[]; priority?: string[]; rule_type?: string[]; component_id?: string; start?: string; end?: string }
export const useAlerts = (p: AlertQuery) => useQuery({ queryKey: keys.alerts(p), queryFn: () => api<Alert[]>(`/alerts${qs(p as any)}`) });
export const useAlertDetail = (id?: string | null) =>
  useQuery({ queryKey: keys.alert(id ?? ""), queryFn: () => api<AlertDetail>(`/alerts/${id}`), enabled: !!id });
export const useAlertRules = () => useQuery({ queryKey: ["alert-rules"], queryFn: () => api<AlertRule[]>("/alert-rules") });

export interface EventQuery { asset_id?: string; component_id?: string; device_id?: string; event_type?: string[]; start?: string; end?: string; limit?: number }
export const useEvents = (p: EventQuery) => useQuery({ queryKey: keys.events(p), queryFn: () => api<EventLog[]>(`/events${qs(p as any)}`) });

export const useInspections = (p: { asset_id?: string; component_id?: string; status?: string; start?: string; end?: string }) =>
  useQuery({ queryKey: keys.inspections(p), queryFn: () => api<Inspection[]>(`/inspections${qs(p)}`) });

export const useSystemStatus = () =>
  useQuery({ queryKey: keys.status, queryFn: () => api<SystemStatus>("/system/status"), refetchInterval: 20_000, retry: 0 });
export const useSettings = () => useQuery({ queryKey: keys.settings, queryFn: () => api<Record<string, any>>("/settings") });

export const useFeatures = (deviceId?: string | null, source?: string, limit = 240) =>
  useQuery({
    queryKey: ["features", deviceId, source, limit],
    queryFn: () => api<Feature[]>(`/sensors/${deviceId}/features${qs({ source, limit })}`),
    enabled: !!deviceId,
  });
export const useReadings = (deviceId?: string | null, source?: string, limit = 300, live = false) =>
  useQuery({
    queryKey: ["readings", deviceId, source, limit],
    queryFn: () => api<Reading[]>(`/sensors/${deviceId}/readings${qs({ source, limit })}`),
    enabled: !!deviceId,
    refetchInterval: live ? 5_000 : false,
  });
export const useBaselines = (deviceId?: string | null) =>
  useQuery({ queryKey: ["baselines", deviceId], queryFn: () => api<Baseline[]>(`/sensors/${deviceId}/baselines`), enabled: !!deviceId });
export const useReports = (assetId?: string) =>
  useQuery({ queryKey: ["reports", assetId], queryFn: () => api<Report[]>(`/reports${qs({ asset_id: assetId })}`), enabled: !!assetId });
export const useModels = () => useQuery({ queryKey: ["models"], queryFn: () => api<ModelRec[]>("/models") });
export const useRulResults = (assetId?: string) =>
  useQuery({ queryKey: ["rul", assetId], queryFn: () => api<RULResult[]>(`/rul/results${qs({ asset_id: assetId })}`), enabled: !!assetId });

/** Mutation helper that invalidates the given query-key prefixes on success. */
export function useApiMutation<TVars, TRes = unknown>(fn: (v: TVars) => Promise<TRes>, invalidate: string[] = []) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => invalidate.forEach((k) => qc.invalidateQueries({ queryKey: [k] })),
  });
}
