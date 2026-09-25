import React, { useState } from 'react';

const PAGE_SIZE = 50;

function cellClass(col, val) {
  if (val === null || val === undefined || val === '') return 'cell-null';
  const v = String(val).toUpperCase().trim();
  if (col === 'Stn_Status' || col.endsWith('_Status')) {
    if (v === 'OK') return 'cell-ok';
    if (v === 'REJECTED') return 'cell-rej';
  }
  if (!isNaN(parseFloat(val)) && col !== 'Engine_Number' && col !== 'Stn_Number' && col !== '_station_group') {
    return 'cell-num';
  }
  return '';
}

/**
 * Renders torque data grouped by station with per-group headers.
 * Drops columns that are entirely zero/null within each station group.
 */
function GroupedTorqueTable({ data, columns }) {
  const groups = [];
  const seen = new Map();
  for (const row of data) {
    const stn = row._station_group || 'Unknown';
    if (!seen.has(stn)) { seen.set(stn, []); groups.push({ stn, rows: seen.get(stn) }); }
    seen.get(stn).push(row);
  }

  const displayCols = columns.filter(c => c !== '_station_group');

  return (
    <div>
      {groups.map(({ stn, rows }) => {
        // Per-group: only show cols with at least one real value
        const activeCols = displayCols.filter(col =>
          rows.some(r => {
            const v = r[col];
            if (v === null || v === undefined || v === '') return false;
            if (typeof v === 'number' && v === 0) return false;
            if (typeof v === 'string' && ['0', '0.0', '0.000', ''].includes(v.trim())) return false;
            return true;
          })
        );
        return (
          <div key={stn} style={{ marginBottom: 20 }}>
            <div className="station-group-header">
              <span className="station-group-icon">🔧</span>
              {stn}
              <span style={{ fontWeight: 400, color: 'var(--text-dim)', marginLeft: 6 }}>
                · {rows.length} engine{rows.length !== 1 ? 's' : ''}
              </span>
            </div>
            <div className="table-wrapper">
              <table>
                <thead>
                  <tr>{activeCols.map(col => <th key={col}>{col}</th>)}</tr>
                </thead>
                <tbody>
                  {rows.map((row, i) => (
                    <tr key={i}>
                      {activeCols.map(col => {
                        const val = row[col];
                        const isEmpty = val === null || val === undefined || val === '';
                        return (
                          <td key={col} className={cellClass(col, val)} title={isEmpty ? '' : String(val)}>
                            {isEmpty ? <span className="cell-null">—</span> : String(val)}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        );
      })}
    </div>
  );
}

export default function DataTable({ data, columns }) {
  const [page, setPage] = useState(0);
  if (!data || data.length === 0) return null;

  // Grouped torque view
  if (columns.includes('_station_group')) {
    return <GroupedTorqueTable data={data} columns={columns} />;
  }

  const totalPages = Math.ceil(data.length / PAGE_SIZE);
  const rows = data.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  return (
    <div>
      <div className="table-wrapper">
        <table>
          <thead>
            <tr>{columns.map(col => <th key={col}>{col}</th>)}</tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr key={i}>
                {columns.map(col => {
                  const val = row[col];
                  const isEmpty = val === null || val === undefined || val === '';
                  return (
                    <td key={col} className={cellClass(col, val)} title={isEmpty ? '' : String(val)}>
                      {isEmpty ? <span className="cell-null">—</span> : String(val)}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {totalPages > 1 && (
        <div className="pagination" style={{ marginTop: 10 }}>
          <button className="page-btn" onClick={() => setPage(0)} disabled={page === 0}>«</button>
          <button className="page-btn" onClick={() => setPage(p => p - 1)} disabled={page === 0}>‹</button>
          <span className="text-xs text-mono text-dim" style={{ padding: '0 6px' }}>{page + 1} / {totalPages}</span>
          <button className="page-btn" onClick={() => setPage(p => p + 1)} disabled={page === totalPages - 1}>›</button>
          <button className="page-btn" onClick={() => setPage(totalPages - 1)} disabled={page === totalPages - 1}>»</button>
        </div>
      )}
    </div>
  );
}
