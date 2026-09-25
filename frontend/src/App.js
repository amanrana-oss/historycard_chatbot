import React, { useState, useCallback } from 'react';
import './index.css';
import Sidebar from './components/Sidebar';
import ChatPanel from './components/ChatPanel';
import AnalyticsPanel from './components/AnalyticsPanel';
import { api } from './api';

const today = new Date().toISOString().split('T')[0];

const DEFAULT_FILTERS = {
  station: '(all)',
  param: '(choose)',
  dateFrom: today,
  dateTo: today,
};

function RELogo() {
  return (
    <div className="re-logo-wrap" title="Royal Enfield">
      <svg width="40" height="40" viewBox="0 0 40 40" fill="none">
        <circle cx="20" cy="20" r="19" stroke="#06b6d4" strokeWidth="1.2" fill="none" opacity="0.4"/>
        <circle cx="20" cy="20" r="12" stroke="#06b6d4" strokeWidth="1.5" fill="none" opacity="0.65"/>
        <circle cx="20" cy="20" r="4.5" fill="#06b6d4" opacity="0.9"/>
        {Array.from({ length: 9 }, (_, i) => {
          const rad = (i * 40 * Math.PI) / 180;
          return (
            <line key={i}
              x1={20 + 6.5 * Math.cos(rad)} y1={20 + 6.5 * Math.sin(rad)}
              x2={20 + 12 * Math.cos(rad)} y2={20 + 12 * Math.sin(rad)}
              stroke="#06b6d4" strokeWidth="1.5" opacity="0.75"
            />
          );
        })}
        <text x="20" y="24" textAnchor="middle" fill="white"
          fontSize="6.5" fontWeight="800" fontFamily="monospace" letterSpacing="0.5">RE</text>
      </svg>
      <div className="re-logo-text-block">
        <span className="re-logo-name">Royal Enfield</span>
        <span className="re-logo-sub">Engine Intelligence</span>
      </div>
    </div>
  );
}

export default function App() {
  const [tab, setTab] = useState('chat');
  const [messages, setMessages] = useState([]);
  const [isLoading, setIsLoading] = useState(false);
  const [filters, setFilters] = useState(DEFAULT_FILTERS);
  const [pendingInput, setPendingInput] = useState('');
  const [analyticsDays, setAnalyticsDays] = useState(7);

  const sendMessage = useCallback(async (question) => {
    if (!question.trim() || isLoading) return;

    setMessages(prev => [...prev, { role: 'user', content: question }]);
    setMessages(prev => [...prev, { role: 'assistant', result: null, question }]);
    setIsLoading(true);

    try {
      const result = await api.chat(
        question,
        filters.station !== '(all)' ? filters.station : null,
        null, null,
      );
      setMessages(prev => {
        const updated = [...prev];
        const idx = updated.findLastIndex(m => m.role === 'assistant' && m.result === null);
        if (idx !== -1) updated[idx] = { role: 'assistant', result, question };
        return updated;
      });
    } catch (err) {
      setMessages(prev => {
        const updated = [...prev];
        const idx = updated.findLastIndex(m => m.role === 'assistant' && m.result === null);
        if (idx !== -1) updated[idx] = {
          role: 'assistant', question,
          result: {
            status: 'error',
            message: `Connection error: ${err.message}. Please check the API server is running.`,
            data: [], columns: [], row_count: 0,
          },
        };
        return updated;
      });
    } finally {
      setIsLoading(false);
    }
  }, [isLoading, filters.station]);

  const handleQuickQuery = useCallback((q) => {
    setPendingInput(q);
    setTab('chat');
    setTimeout(() => sendMessage(q), 100);
  }, [sendMessage]);

  return (
    <div className="app-shell">
      <Sidebar filters={filters} onFilterChange={setFilters} onQuickQuery={handleQuickQuery} />

      <div className="main-area">
        <div className="tab-bar">
          <button className={`tab ${tab === 'chat' ? 'active' : ''}`} onClick={() => setTab('chat')}>
            ◎ CHAT
          </button>
          <button className={`tab ${tab === 'analytics' ? 'active' : ''}`} onClick={() => setTab('analytics')}>
            ▦ ANALYTICS
          </button>
          {tab === 'analytics' && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, paddingLeft: 12 }}>
              <span className="text-xs text-mono text-dim">Last</span>
              {[7, 14, 30].map(d => (
                <button key={d} className={`page-btn ${analyticsDays === d ? 'active' : ''}`}
                  onClick={() => setAnalyticsDays(d)}>{d}d</button>
              ))}
            </div>
          )}
          <div style={{ marginLeft: 'auto', paddingRight: 16, display: 'flex', alignItems: 'center' }}>
            <RELogo />
          </div>
        </div>

        {tab === 'chat' && (
          <ChatPanel messages={messages} isLoading={isLoading} onSend={sendMessage} defaultInput={pendingInput} />
        )}
        {tab === 'analytics' && (
          <AnalyticsPanel days={analyticsDays} />
        )}
      </div>
    </div>
  );
}
