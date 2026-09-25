import React, { useEffect, useState } from 'react';
import { api } from '../api';
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
  LineChart, Line, CartesianGrid, Legend
} from 'recharts';

function LoadingCard({ title }) {
  return (
    <div className="analytics-card">
      <h3>{title}</h3>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '20px 0', color: 'var(--text-dim)' }}>
        <div className="spinner" />
        <span className="text-mono text-xs">Loading...</span>
      </div>
    </div>
  );
}

function ErrorCard({ title, error }) {
  return (
    <div className="analytics-card">
      <h3>{title}</h3>
      <div className="status-badge badge-error" style={{ marginTop: 8 }}>{error}</div>
    </div>
  );
}

const CHART_COLORS = [
  '#2563eb', '#06b6d4', '#10b981', '#f59e0b',
  '#8b5cf6', '#ec4899', '#ef4444', '#84cc16',
];

const CustomTooltip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null;
  return (
    <div style={{
      background: 'var(--bg-elevated)',
      border: '1px solid var(--border)',
      borderRadius: 8,
      padding: '8px 12px',
      fontSize: 11,
      fontFamily: 'var(--font-mono)',
    }}>
      <div style={{ color: 'var(--text-secondary)', marginBottom: 4 }}>{label}</div>
      {payload.map((p, i) => (
        <div key={i} style={{ color: p.color }}>
          {p.name}: <strong>{p.value}</strong>
        </div>
      ))}
    </div>
  );
};

export default function AnalyticsPanel({ days = 7 }) {
  const [failures, setFailures] = useState(null);
  const [rejections, setRejections] = useState(null);
  const [rework, setRework] = useState(null);
  const [trend, setTrend] = useState(null);

  const [failErr, setFailErr] = useState(null);
  const [rejErr, setRejErr] = useState(null);
  const [reworkErr, setReworkErr] = useState(null);
  const [trendErr, setTrendErr] = useState(null);

  useEffect(() => {
    api.stationFailures(null, null, days)
      .then(r => setFailures(r.data))
      .catch(e => setFailErr(e.message));

    api.rejectionReasons(null, null, days)
      .then(r => setRejections(r.data))
      .catch(e => setRejErr(e.message));

    api.reworkStations(null, null, days)
      .then(r => setRework(r.data))
      .catch(e => setReworkErr(e.message));

    api.failureTrend(days)
      .then(r => setTrend(r.data))
      .catch(e => setTrendErr(e.message));
  }, [days]);

  const axisStyle = { fill: 'var(--text-dim)', fontSize: 10, fontFamily: 'var(--font-mono)' };

  return (
    <div className="analytics-panel">
      <div style={{ marginBottom: 20 }}>
        <h2 style={{ fontFamily: 'var(--font-mono)', fontSize: 13, color: 'var(--text-secondary)', letterSpacing: '0.06em' }}>
          PRODUCTION ANALYTICS — LAST {days} DAYS
        </h2>
        <p style={{ fontSize: 12, color: 'var(--text-dim)', marginTop: 4 }}>
          Real-time insights from the assembly line
        </p>
      </div>

      <div className="analytics-grid">
        {/* Station Failures */}
        {failErr ? <ErrorCard title="STATION FAILURES" error={failErr} /> :
         !failures ? <LoadingCard title="STATION FAILURES" /> : (
          <div className="analytics-card">
            <h3>Which station fails the most?</h3>
            {failures.length === 0 ? (
              <p className="text-xs text-dim">No failure data found</p>
            ) : (
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={failures.slice(0, 10)} margin={{ top: 4, right: 4, left: -20, bottom: 4 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                  <XAxis dataKey="Stn_Number" tick={axisStyle} />
                  <YAxis tick={axisStyle} />
                  <Tooltip content={<CustomTooltip />} />
                  <Bar dataKey="failure_count" fill="#ef4444" radius={[3, 3, 0, 0]} name="Failures" />
                </BarChart>
              </ResponsiveContainer>
            )}
            <div style={{ marginTop: 12 }}>
              {failures.slice(0, 5).map((row, i) => (
                <div className="bar-row" key={i}>
                  <span className="bar-label">{row.Stn_Number}</span>
                  <div className="bar-track">
                    <div
                      className="bar-fill"
                      style={{
                        width: `${Math.min(100, (parseInt(row.failure_count) / parseInt(failures[0].failure_count)) * 100)}%`,
                        background: `hsl(${10 + i * 15}, 80%, 55%)`,
                      }}
                    />
                  </div>
                  <span className="bar-value">{row.failure_count}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Top Rejection Reasons */}
        {rejErr ? <ErrorCard title="REJECTION REASONS" error={rejErr} /> :
         !rejections ? <LoadingCard title="REJECTION REASONS" /> : (
          <div className="analytics-card">
            <h3>Top rejection reasons this week</h3>
            {rejections.length === 0 ? (
              <p className="text-xs text-dim">No rejection data found</p>
            ) : (
              <div style={{ marginTop: 4 }}>
                {rejections.slice(0, 8).map((row, i) => (
                  <div className="bar-row" key={i}>
                    <span className="bar-label" style={{ width: 90, fontSize: 10, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }} title={row.reason}>
                      {row.reason?.length > 12 ? row.reason.slice(0, 12) + '…' : row.reason}
                    </span>
                    <div className="bar-track">
                      <div
                        className="bar-fill"
                        style={{
                          width: `${Math.min(100, (parseInt(row.count) / parseInt(rejections[0].count)) * 100)}%`,
                          background: CHART_COLORS[i % CHART_COLORS.length],
                        }}
                      />
                    </div>
                    <span className="bar-value">{row.count}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Rework by Station */}
        {reworkErr ? <ErrorCard title="REWORK STATIONS" error={reworkErr} /> :
         !rework ? <LoadingCard title="REWORK STATIONS" /> : (
          <div className="analytics-card">
            <h3>Which ML station causes max rework?</h3>
            {rework.length === 0 ? (
              <p className="text-xs text-dim">No rework data found</p>
            ) : (
              <ResponsiveContainer width="100%" height={200}>
                <BarChart data={rework.slice(0, 10)} margin={{ top: 4, right: 4, left: -20, bottom: 4 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                  <XAxis dataKey="Stn_Number" tick={axisStyle} />
                  <YAxis tick={axisStyle} />
                  <Tooltip content={<CustomTooltip />} />
                  <Bar dataKey="total_rework" fill="#f59e0b" radius={[3, 3, 0, 0]} name="Total Rework" />
                  <Bar dataKey="engines_reworked" fill="#8b5cf6" radius={[3, 3, 0, 0]} name="Engines" />
                </BarChart>
              </ResponsiveContainer>
            )}
          </div>
        )}

        {/* Failure Trend */}
        {trendErr ? <ErrorCard title="FAILURE TREND" error={trendErr} /> :
         !trend ? <LoadingCard title="FAILURE TREND" /> : (
          <div className="analytics-card">
            <h3>Failure trend over last {days} days</h3>
            {trend.length === 0 ? (
              <p className="text-xs text-dim">No trend data found</p>
            ) : (
              <ResponsiveContainer width="100%" height={220}>
                <LineChart data={trend} margin={{ top: 4, right: 4, left: -20, bottom: 4 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                  <XAxis dataKey="date" tick={axisStyle} />
                  <YAxis tick={axisStyle} />
                  <Tooltip content={<CustomTooltip />} />
                  <Legend wrapperStyle={{ fontSize: 10, fontFamily: 'var(--font-mono)' }} />
                  <Line
                    type="monotone" dataKey="failures" stroke="#ef4444"
                    strokeWidth={2} dot={false} name="Failures"
                  />
                  <Line
                    type="monotone" dataKey="reworks" stroke="#f59e0b"
                    strokeWidth={2} dot={false} name="Reworks"
                  />
                  <Line
                    type="monotone" dataKey="engines_processed" stroke="#06b6d4"
                    strokeWidth={1.5} dot={false} strokeDasharray="4 2" name="Engines"
                  />
                </LineChart>
              </ResponsiveContainer>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
