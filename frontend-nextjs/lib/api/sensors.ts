/**
 * Sensors API — live devices (phones, GPS trackers) added to the organization.
 * Adding, editing and removing is admin-only; everyone in the org can view.
 */

import { apiClient } from "./client";

export type SensorType = "phone" | "gps_tracker";
export type SensorStatus = "live" | "offline" | "waiting" | "paused";

export interface SensorEnvelope<T = Record<string, unknown>> {
  v: number;
  sensor_id: string;
  sensor_type: SensorType;
  kind: string;
  ts: number;
  received_ts: number;
  data: T;
}

export interface PositionData {
  lat: number;
  lon: number;
  accuracy_m: number | null;
  alt_m: number | null;
  course_deg: number | null;
  speed_mps: number | null;
}

export interface OrientationData {
  heading_deg: number | null;
  heading_source: string | null;
  pitch_deg: number | null;
  roll_deg: number | null;
}

export interface StatusData {
  battery_pct: number | null;
  charging: boolean | null;
}

export interface SensorSetup {
  hub_reachable: boolean;
  // phone
  pair_url?: string | null;
  // gps_tracker
  server_host?: string | null;
  server_port?: number;
  server_url?: string | null;
  tcp_endpoint?: string | null; // hosted Traccar: "host:port" for hardware trackers (raw TCP)
  device_id?: string;
}

export interface WatchRule {
  id?: string;
  label: string; // what to alert on, e.g. "Person", "Bird"
  question?: string; // precise yes/no question for the decision model
  threshold?: number;
}

export interface WatchConfig {
  enabled: boolean;
  interval_s?: number;
  motion_only?: boolean; // only ask the model when the picture changed (saves cost)
  rules: WatchRule[];
}

/** The SoldierIQ agent's automatic review of an alert frame. */
export interface AlertAssessment {
  status: "reviewing" | "done" | "failed" | "skipped";
  threat?: "low" | "medium" | "high" | null;
  text?: string;
  model?: string;
}

export interface SensorAlert {
  id: string;
  sensor_id: string;
  sensor_name: string;
  rule_id: string;
  label: string;
  probability: number;
  model: string;
  captured_at: string;
  created_at: string;
  lat: number | null;
  lon: number | null;
  heading: number | null;
  acknowledged: boolean;
  image_url: string;
  assessment: AlertAssessment | null;
}

export interface Sensor {
  id: string;
  name: string;
  sensor_type: SensorType;
  identifier: string | null;
  enabled: boolean;
  status: SensorStatus;
  last_seen: string | null;
  created_at: string;
  has_camera: boolean;
  latest: {
    position?: SensorEnvelope<PositionData>;
    orientation?: SensorEnvelope<OrientationData>;
    status?: SensorEnvelope<StatusData>;
    detection?: SensorEnvelope<{ model: string; probabilities: Record<string, number> }>;
  };
  watch?: WatchConfig | null;
  setup?: SensorSetup;
}

export interface SensorList {
  sensors: Sensor[];
  is_admin: boolean;
}

export const sensorsApi = {
  list: async (): Promise<SensorList> => (await apiClient.get<SensorList>("/sensors")).data,

  create: async (body: { name: string; sensor_type: SensorType; identifier?: string }): Promise<Sensor> =>
    (await apiClient.post<Sensor>("/sensors", body)).data,

  update: async (id: string, body: { name?: string; enabled?: boolean; watch?: WatchConfig }): Promise<Sensor> =>
    (await apiClient.patch<Sensor>(`/sensors/${id}`, body)).data,

  remove: async (id: string): Promise<void> => {
    await apiClient.delete(`/sensors/${id}`);
  },

  newPairing: async (id: string): Promise<Sensor> => (await apiClient.post<Sensor>(`/sensors/${id}/pairing`)).data,

  alerts: async (params: { since?: string; sensor_id?: string; limit?: number; ids?: string } = {}): Promise<{ alerts: SensorAlert[]; server_time: string }> =>
    (await apiClient.get("/sensors/alerts", { params })).data,

  acknowledge: async (alertId: string): Promise<void> => {
    await apiClient.post(`/sensors/alerts/${alertId}/ack`);
  },

  streamUrl: async (id: string): Promise<{ stream_url: string; frame_url: string; expires: number }> =>
    (await apiClient.get(`/sensors/${id}/stream-url`)).data,
};
