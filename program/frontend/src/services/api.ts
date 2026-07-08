const API_BASE = import.meta.env.VITE_API_BASE_URL || '/api';

export async function request(path: string, options: RequestInit = {}) {
  const url = `${API_BASE}${path}`;
  const headers = {
    'Content-Type': 'application/json',
    ...(options.headers || {}),
  };

  try {
    const res = await fetch(url, { ...options, headers });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Request failed with status ${res.status}`);
    }
    return await res.json();
  } catch (error: any) {
    console.error(`API Error [${url}]:`, error.message);
    throw error;
  }
}

// Whitelist CRUD
export const whitelistAPI = {
  list: () => request('/whitelist'),
  add: (plateNumber: string) => request('/whitelist', {
    method: 'POST',
    body: JSON.stringify({ plate_number: plateNumber }),
  }),
  remove: (plateNumber: string) => request(`/whitelist/${encodeURIComponent(plateNumber)}`, {
    method: 'DELETE',
  }),
};

// Statistical Analytics
export const statsAPI = {
  vehicles: (zone?: string, minutes: number = 30) => {
    const q = zone ? `?zone=${encodeURIComponent(zone)}&minutes=${minutes}` : `?minutes=${minutes}`;
    return request(`/stats/vehicles${q}`);
  },
  violations: (zone?: string, minutes: number = 60) => {
    const q = zone ? `?zone=${encodeURIComponent(zone)}&minutes=${minutes}` : `?minutes=${minutes}`;
    return request(`/stats/violations${q}`);
  },
  anomalies: (minutes: number = 60) => request(`/stats/anomalies?minutes=${minutes}`),
  system: (minutes: number = 15) => request(`/stats/system?minutes=${minutes}`),
};

// System configs
export const configAPI = {
  getModels: () => request('/configs/models'),
  updateModel: (modelName: string, enabled: boolean, confidenceThreshold: number) => request('/configs/models', {
    method: 'PUT',
    body: JSON.stringify({
      model_name: modelName,
      enabled,
      confidence_threshold: confidenceThreshold,
    }),
  }),
  getZones: () => request('/configs/zones'),
  updateZones: (zones: any[]) => request('/configs/zones', {
    method: 'PUT',
    body: JSON.stringify(zones),
  }),
  health: () => request('/health'),
};
