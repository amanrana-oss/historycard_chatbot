import React, { useRef, useEffect, useCallback } from 'react';
import DataTable from './DataTable';

function StatusBadge({ status }) {
  const map = {
    success: ['badge-ok', '✓ Data found'],
    empty:   ['badge-warn', '⚠ No data'],
    error:   ['badge-error', '✗ Error'],
    not_found: ['badge-error', '✗ Not found'],
    clarification: ['badge-info', '? Clarification needed'],
  };
  const [cls, label] = map[status] || ['badge-info', status];
  return <span className={`status-badge ${cls}`}>{label}</span>;
}

function AssistantMessage({ msg }) {
  const { result, question } = msg;

  if (!result) {
    return (
      <div className="typing-indicator">
        <div className="spinner" />
        Thinking...
      </div>
    );
  }

  const isError = ['error', 'not_found', 'empty', 'clarification'].includes(result.status);

  return (
    <div className="bubble" style={{ maxWidth: '100%' }}>
      {/* Status + meta row */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
        <StatusBadge status={result.status} />
        {result.row_count > 0 && (
          <span className="text-xs text-mono text-dim">
            {result.row_count} row{result.row_count !== 1 ? 's' : ''}
            {result.columns?.length ? ` · ${result.columns.length} cols` : ''}
            {result.cached ? ' · cached' : ''}
          </span>
        )}
        {result.meta?.parameter && (
          <span className="status-badge badge-info">
            {result.meta.parameter}
          </span>
        )}
      </div>

      {/* Message for error/empty states */}
      {result.message && (
        <div style={{
          padding: '10px 12px',
          borderRadius: 8,
          background: isError ? 'rgba(239,68,68,0.08)' : 'rgba(245,158,11,0.08)',
          border: `1px solid ${isError ? 'rgba(239,68,68,0.2)' : 'rgba(245,158,11,0.2)'}`,
          color: isError ? 'var(--accent-red)' : 'var(--accent-amber)',
          fontSize: 13,
          lineHeight: 1.6,
          marginBottom: result.data?.length ? 10 : 0,
        }}>
          {result.message}
        </div>
      )}

      {/* Data table */}
      {result.data?.length > 0 && (
        <>
          <DataTable data={result.data} columns={result.columns} />
          <div className="result-meta">
            <div className="result-meta-left">
              <span>Query took ~{result.query_ms || '—'}ms</span>
            </div>
            <button
              className="btn btn-ghost btn-sm"
              onClick={() => {
                const csv = [result.columns.join(',')];
                result.data.forEach(row => {
                  csv.push(result.columns.map(c => {
                    const v = row[c] ?? '';
                    return String(v).includes(',') ? `"${v}"` : v;
                  }).join(','));
                });
                const blob = new Blob([csv.join('\n')], { type: 'text/csv' });
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url; a.download = 'engine_history.csv'; a.click();
                URL.revokeObjectURL(url);
              }}
            >
              ⬇ Download CSV
            </button>
          </div>
        </>
      )}
    </div>
  );
}

export default function ChatPanel({ messages, isLoading, onSend, defaultInput }) {
  const bottomRef = useRef(null);
  const inputRef = useRef(null);
  const [inputVal, setInputVal] = React.useState('');

  // Inject quick query
  useEffect(() => {
    if (defaultInput) {
      setInputVal(defaultInput);
      inputRef.current?.focus();
    }
  }, [defaultInput]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isLoading]);

  const handleSend = useCallback(() => {
    const q = inputVal.trim();
    if (!q || isLoading) return;
    onSend(q);
    setInputVal('');
  }, [inputVal, isLoading, onSend]);

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <>
      <div className="chat-area">
        {messages.length === 0 ? (
          <div className="welcome-state">
            <div className="big-icon">⚙</div>
            <h2>ENGINE HISTORY INTELLIGENCE</h2>
            <p>
              Ask natural language questions about engine assembly history,
              station data, barcode scans, torque values, and production analytics.
            </p>
            <p className="text-xs text-mono text-dim" style={{ marginTop: 8 }}>
              Try: "barcode for ML-50 today" or "torque for ML-43 yesterday"
            </p>
          </div>
        ) : (
          messages.map((msg, i) => (
            <div key={i} className={`message message-${msg.role}`}>
              {msg.role === 'user' ? (
                <>
                  <div className="bubble">{msg.content}</div>
                  <span className="message-meta">You</span>
                </>
              ) : (
                <>
                  <span className="message-meta">Engine Intelligence</span>
                  <AssistantMessage msg={msg} />
                </>
              )}
            </div>
          ))
        )}
        {isLoading && (
          <div className="message message-assistant">
            <span className="message-meta">Engine Intelligence</span>
            <div className="typing-indicator">
              <div className="spinner" />
              Understanding your question...
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      <div className="input-bar">
        <textarea
          ref={inputRef}
          className="chat-input"
          placeholder="Ask about engine history, barcodes, torque, leak values, or station status..."
          value={inputVal}
          onChange={e => setInputVal(e.target.value)}
          onKeyDown={handleKeyDown}
          rows={1}
        />
        <button
          className="send-btn"
          onClick={handleSend}
          disabled={!inputVal.trim() || isLoading}
          title="Send (Enter)"
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="m22 2-7 20-4-9-9-4Z" />
            <path d="M22 2 11 13" />
          </svg>
        </button>
      </div>
    </>
  );
}
