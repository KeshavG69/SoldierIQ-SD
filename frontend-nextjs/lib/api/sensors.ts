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
  device_id?: string;
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
  };
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

  update: async (id: string, body: { name?: string; enabled?: boolean }): Promise<Sensor> =>
    (await apiClient.patch<Sensor>(`/sensors/${id}`, body)).data,

  remove: async (id: string): Promise<void> => {
    await apiClient.delete(`/sensors/${id}`);
  },

  newPairing: async (id: string): Promise<Sensor> => (await apiClient.post<Sensor>(`/sensors/${id}/pairing`)).data,

  streamUrl: async (id: string): Promise<{ stream_url: string; frame_url: string; expires: number }> =>
    (await apiClient.get(`/sensors/${id}/stream-url`)).data,
};
