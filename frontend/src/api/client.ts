export type ServiceStatus = 'healthy' | 'unhealthy'

export interface HealthResponse {
  status: 'healthy' | 'degraded'
  api: { status: ServiceStatus }
  database: { status: ServiceStatus }
  redis: { status: ServiceStatus }
}

const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000/api/v1'

export async function getHealth(signal?: AbortSignal): Promise<HealthResponse> {
  const response = await fetch(`${API_URL}/health`, { signal })

  if (!response.ok) {
    throw new Error(`Health request failed with status ${response.status}`)
  }

  return response.json() as Promise<HealthResponse>
}

