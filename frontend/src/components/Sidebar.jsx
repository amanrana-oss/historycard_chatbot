import React from 'react';

// ML-01 through ML-54 — hardcoded, no API dependency
const ALL_STATIONS = Array.from({ length: 54 }, (_, i) => `ML-${String(i + 1).padStart(2, '0')}`);

const EXAMPLES = [
  'summary of engine J3A5FNS2048940',
  'show timeline of engine J3A5FNS2048940',
  'barcode for ML-50 today',
  'torque value of ML-10 today',
  'leak value today',
  'show all barcodes this week',
  'torque for ML-43 yesterday',
  'station status for ML-47 today',
  'show first failure of engine J3A5FNS2048940',
  'compare engine J3A5FNS2048940 and J3A5FNS2048941',
  'show ML-39 details for engine J3A5FNS2048940',
];

export default function Sidebar({ onQuickQuery, onFilterChange, filters }) {
  const handleQuickQuery = () => {
    const { station, param, dateFrom, dateTo } = filters;
    if (!param || param === '(choose)') { alert('Pick a parameter first.'); return; }
    let stationPart = station && station !== '(all)' ? ` for ${station}` : '';
    let datePart = '';
    if (dateFrom && dateTo) {
      datePart = dateFrom === dateTo ? ` on ${dateFrom}` : ` from ${dateFrom} to ${dateTo}`;
    } else {
      datePart = ' today';
    }
    onQuickQuery(`show ${param}${stationPart}${datePart}`);
  };

  return (
    <aside className="sidebar">
      <div className="sidebar-logo">
        <div className="logo-row">
          <svg className="logo-gear" width="34" height="34" viewBox="0 0 34 34" fill="none">
            <circle cx="17" cy="17" r="16" stroke="#06b6d4" strokeWidth="1.2" fill="none" opacity="0.35"/>
            <circle cx="17" cy="17" r="10" stroke="#06b6d4" strokeWidth="1.4" fill="none" opacity="0.6"/>
            <circle cx="17" cy="17" r="4" fill="#06b6d4"/>
            {Array.from({ length: 9 }, (_, i) => {
              const rad = (i * 40 * Math.PI) / 180;
              return (
                <line key={i}
                  x1={17 + 5.5 * Math.cos(rad)} y1={17 + 5.5 * Math.sin(rad)}
                  x2={17 + 10 * Math.cos(rad)} y2={17 + 10 * Math.sin(rad)}
                  stroke="#06b6d4" strokeWidth="1.4" opacity="0.75"
                />
              );
            })}
          </svg>
          <div>
            <h1>Engine Intelligence</h1>
            <p>Royal Enfield · Assembly v2</p>
          </div>
        </div>
      </div>

      <div className="sidebar-section">
        <h3>Quick Filters</h3>

        <div className="form-group">
          <label>Station</label>
          <select className="form-control" value={filters.station}
            onChange={e => onFilterChange({ ...filters, station: e.target.value })}>
            <option value="(all)">(all stations)</option>
            {ALL_STATIONS.map(s => <option key={s} value={s}>{s}</option>)}
          </select>
        </div>

        <div className="form-group">
          <label>Parameter</label>
          <select className="form-control" value={filters.param}
            onChange={e => onFilterChange({ ...filters, param: e.target.value })}>
            <option value="(choose)">(choose)</option>
            <option value="barcode">Barcode</option>
            <option value="torque">Torque</option>
            <option value="leak">Leak</option>
            <option value="status">Status</option>
          </select>
        </div>

        <div className="form-group">
          <label>Date From</label>
          <input type="date" className="form-control" value={filters.dateFrom}
            onChange={e => onFilterChange({ ...filters, dateFrom: e.target.value })} />
        </div>

        <div className="form-group">
          <label>Date To</label>
          <input type="date" className="form-control" value={filters.dateTo}
            onChange={e => onFilterChange({ ...filters, dateTo: e.target.value })} />
        </div>

        <button className="btn btn-primary" onClick={handleQuickQuery}>
          ▶ Run Quick Query
        </button>
      </div>

      <div className="divider" />

      <div className="sidebar-section">
        <h3>Examples</h3>
        {EXAMPLES.map((ex, i) => (
          <button key={i} className="example-pill" onClick={() => onQuickQuery(ex)}>{ex}</button>
        ))}
      </div>

      <div style={{ flex: 1 }} />

      <div style={{ padding: '12px 16px', borderTop: '1px solid var(--border)' }}>
        <p className="text-xs text-mono text-dim">Queries cached 60s · 100+ concurrent users</p>
      </div>
    </aside>
  );
}
