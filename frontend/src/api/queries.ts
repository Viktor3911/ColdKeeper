// TanStack Query hooks: one place for keys, refresh intervals and invalidation after changes.
import { useMutation, useQuery, useQueryClient, type QueryKey } from "@tanstack/react-query";

import { api } from "./client";
import type {
  BindingCode,
  EquipmentCard,
  Incident,
  Inventory,
  IssuedToken,
  Journal,
  Meta,
  PointOverview,
  RawJournal,
  Recipients,
  Sensor,
  SensorDetail,
  SeriesPoint,
} from "./types";

// The overview is polled; a WebSocket is not needed for minute-level readings.
export const LIVE_REFRESH_MS = 30_000;

export function useMeta() {
  return useQuery({ queryKey: ["meta"], queryFn: () => api.get<Meta>("/api/v1/meta"), staleTime: Infinity });
}

export function useOverview() {
  return useQuery({
    queryKey: ["overview"],
    queryFn: () => api.get<PointOverview[]>("/api/v1/overview"),
    refetchInterval: LIVE_REFRESH_MS,
  });
}

export function useInventory() {
  return useQuery({ queryKey: ["inventory"], queryFn: () => api.get<Inventory>("/api/v1/inventory") });
}

export function useEquipmentCard(equipmentId: string) {
  return useQuery({
    queryKey: ["equipment", equipmentId],
    queryFn: () => api.get<EquipmentCard>(`/api/v1/equipment/${equipmentId}`),
    refetchInterval: LIVE_REFRESH_MS,
  });
}

/** Chart data for the last `hours`; the window is computed at fetch time, so polling keeps it sliding. */
export function useSeries(pointId: string, hours: number) {
  return useQuery({
    queryKey: ["series", pointId, hours],
    queryFn: () => {
      const end = new Date(Date.now() + 5 * 60_000);
      const start = new Date(end.getTime() - hours * 3_600_000);
      return api.get<SeriesPoint[]>(`/api/v1/points/${pointId}/series`, {
        start: start.toISOString(),
        end: end.toISOString(),
      });
    },
    refetchInterval: LIVE_REFRESH_MS,
  });
}

export function useSensors() {
  return useQuery({
    queryKey: ["sensors"],
    queryFn: () => api.get<Sensor[]>("/api/v1/sensors"),
    refetchInterval: LIVE_REFRESH_MS,
  });
}

export function useSensorDetail(sensorId: string | null) {
  return useQuery({
    queryKey: ["sensor", sensorId],
    queryFn: () => api.get<SensorDetail>(`/api/v1/sensors/${sensorId ?? ""}`),
    enabled: sensorId !== null,
  });
}

export interface JournalQuery {
  first: string;
  last: string;
  site_id?: string;
  equipment_id?: string;
}

export function useDailyJournal(query: JournalQuery) {
  return useQuery({
    queryKey: ["journal", "daily", query],
    queryFn: () => api.get<Journal>("/api/v1/journal/daily", { ...query }),
  });
}

export function useRawJournal(query: JournalQuery, enabled: boolean) {
  return useQuery({
    queryKey: ["journal", "raw", query],
    queryFn: () => api.get<RawJournal>("/api/v1/journal/raw", { ...query }),
    enabled,
  });
}

export function useIncidents(onlyOpen: boolean) {
  return useQuery({
    queryKey: ["incidents", onlyOpen],
    queryFn: () => api.get<Incident[]>("/api/v1/incidents", { open: onlyOpen }),
    refetchInterval: LIVE_REFRESH_MS,
  });
}

export function useRecipients() {
  return useQuery({ queryKey: ["recipients"], queryFn: () => api.get<Recipients>("/api/v1/recipients") });
}

/** A mutation that refreshes the given cached queries on success. */
export function useChange<TArgs, TResult = unknown>(action: (args: TArgs) => Promise<TResult>, refresh: QueryKey[]) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: action,
    onSuccess: async () => {
      await Promise.all(refresh.map((queryKey) => client.invalidateQueries({ queryKey })));
    },
  });
}

export const sensorActions = {
  register: (body: { hardware_id: string; kind: "physical" | "simulated"; model: string }) =>
    api.post<IssuedToken>("/api/v1/sensors", body),
  reissue: (sensorId: string) => api.post<IssuedToken>(`/api/v1/sensors/${sensorId}/token`),
  revoke: (sensorId: string) => api.delete(`/api/v1/sensors/${sensorId}/token`),
  assign: (args: { sensorId: string; pointId: string; startsAt: string | null }) =>
    api.post(`/api/v1/sensors/${args.sensorId}/assignment`, { point_id: args.pointId, starts_at: args.startsAt }),
  unassign: (sensorId: string) => api.delete(`/api/v1/sensors/${sensorId}/assignment`),
};

export const recipientActions = {
  code: () => api.post<BindingCode>("/api/v1/recipients/code"),
  setActive: (args: { id: string; active: boolean }) =>
    api.post(`/api/v1/recipients/${args.id}/active`, { active: args.active }),
};
