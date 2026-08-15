/**
 * TAK (Team Awareness Kit) API Client
 * Handles TAK configuration for organizations
 */

import { apiClient } from './client';

export interface TAKConfig {
  organization_id: string;
  tak_enabled: boolean;
  tak_host: string;
  tak_port: number;
  tak_username: string;
  agent_callsign: string;
}

export interface TAKConfigRequest {
  tak_enabled: boolean;
  tak_host: string;
  tak_port: number;
  tak_username: string;
  tak_password: string;
  agent_callsign?: string;
}

export interface TAKStatus {
  tak_configured: boolean;
  tak_enabled: boolean;
}

/**
 * Configure TAK settings for the organization (Admin only)
 */
export async function configureTAK(config: TAKConfigRequest): Promise<TAKConfig> {
  const response = await apiClient.post<TAKConfig>('/tak/config', config);
  return response.data;
}

/**
 * Get TAK configuration for the organization
 */
export async function getTAKConfig(): Promise<TAKConfig> {
  const response = await apiClient.get<TAKConfig>('/tak/config');
  return response.data;
}

/**
 * Get TAK status (configured/enabled)
 */
export async function getTAKStatus(): Promise<TAKStatus> {
  const response = await apiClient.get<TAKStatus>('/tak/status');
  return response.data;
}

/**
 * Delete TAK configuration (Admin only)
 */
export async function deleteTAKConfig(): Promise<void> {
  await apiClient.delete('/tak/config');
}

/**
 * Get TAK credentials for chat (includes password)
 * This is used to pass credentials to chat API
 */
export interface TAKCredentials {
  tak_host: string;
  tak_port: number;
  tak_username: string;
  tak_password: string;
  agent_callsign: string;
}
