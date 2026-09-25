const BASE_URL = process.env.REACT_APP_API_URL || '';

async function apiFetch(path, options = {}) {
  const res = await fetch(`${BASE_URL}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Unknown error' }));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

export const api = {
  health: () => apiFetch('/health'),

  chat: (question, stationFilter, dateFrom, dateTo) =>
    apiFetch('/chat', {
      method: 'POST',
      body: JSON.stringify({
        question,
        station_filter: stationFilter,
        date_from: dateFrom,
        date_to: dateTo,
      }),
    }),

  getStations: () => apiFetch('/stations'),

  stationFailures: (dateFrom, dateTo, days) =>
    apiFetch('/analytics/station-failures', {
      method: 'POST',
      body: JSON.stringify({ query_type: 'station_failures', date_from: dateFrom, date_to: dateTo, days }),
    }),

  rejectionReasons: (dateFrom, dateTo, days) =>
    apiFetch('/analytics/rejection-reasons', {
      method: 'POST',
      body: JSON.stringify({ query_type: 'rejection_reasons', date_from: dateFrom, date_to: dateTo, days }),
    }),

  reworkStations: (dateFrom, dateTo, days) =>
    apiFetch('/analytics/rework-stations', {
      method: 'POST',
      body: JSON.stringify({ query_type: 'rework_stations', date_from: dateFrom, date_to: dateTo, days }),
    }),

  failureTrend: (days) =>
    apiFetch('/analytics/failure-trend', {
      method: 'POST',
      body: JSON.stringify({ query_type: 'failure_trend', days }),
    }),

  exportCsv: async (question, stationFilter, dateFrom, dateTo) => {
    const res = await fetch(`${BASE_URL}/export/csv`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        question,
        station_filter: stationFilter,
        date_from: dateFrom,
        date_to: dateTo,
      }),
    });
    if (!res.ok) throw new Error('Export failed');
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'engine_history.csv';
    a.click();
    URL.revokeObjectURL(url);
  },
};
