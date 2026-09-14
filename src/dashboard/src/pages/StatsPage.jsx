import { useCallback, useEffect, useState } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { AdminAuthError, fetchAdminLogs, fetchAdminStats } from '../api'

// ─── Helpers ─────────────────────────────────────────────────────────────────

const DAY_MS = 24 * 60 * 60 * 1000

function isoDay(d) {
  return d.toISOString().slice(0, 10)
}

function sevenDaysAgo() {
  return isoDay(new Date(Date.now() - 6 * DAY_MS))
}

function fmtUsd(v) {
  return '$' + Number(v ?? 0).toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 4 })
}

function fmtTokens(v) {
  return Number(v ?? 0).toLocaleString('en-US')
}

function fmtPct(v) {
  return Number(v ?? 0).toFixed(2) + '%'
}

const TIER_COLORS = { T1: '#22c55e', T2: '#f59e0b', T3: '#ef4444' }

const STATUS_STYLES = {
  ok: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  error: 'bg-rose-50 text-rose-700 border-rose-200',
  pending: 'bg-amber-50 text-amber-700 border-amber-200',
  incomplete: 'bg-zinc-100 text-zinc-600 border-zinc-200',
}

function StatusBadge({ status }) {
  const style = STATUS_STYLES[status] || STATUS_STYLES.incomplete
  return (
    <span className={`inline-flex items-center px-2.5 py-0.5 text-xs font-semibold rounded-full border ${style}`}>
      {status}
    </span>
  )
}

function KpiCard({ label, value, sub, accent, title }) {
  return (
    <div className="bg-white border border-zinc-200/90 rounded-2xl p-3.5 sm:p-4 shadow-xs" title={title}>
      <div className="text-[10px] sm:text-[11px] font-bold text-zinc-400 uppercase tracking-wider">{label}</div>
      <div className={`mt-1 text-lg sm:text-2xl font-bold ${accent || 'text-zinc-900'} truncate`}>{value}</div>
      {sub && <div className="text-[10px] sm:text-[11px] text-zinc-400 mt-0.5 sm:mt-1 truncate">{sub}</div>}
    </div>
  )
}

function ChartCard({ title, children }) {
  return (
    <div className="bg-white border border-zinc-200/90 rounded-2xl p-5 shadow-xs">
      <h3 className="text-sm font-semibold text-zinc-800 mb-4">{title}</h3>
      {children}
    </div>
  )
}

function TokenUsagePanel({ items, totalTokens }) {
  return (
    <div className="bg-white border border-zinc-200/90 rounded-2xl p-5 shadow-xs">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-semibold text-zinc-900">Token usage theo model</h3>
        <span className="text-xs text-zinc-400">
          Tổng:{' '}
          <span className="font-bold text-zinc-900 font-mono">{fmtTokens(totalTokens)}</span> tokens
        </span>
      </div>
      {items.length === 0 ? (
        <p className="text-sm text-zinc-400 py-6 text-center">Chưa có token nào được dùng.</p>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs font-semibold text-zinc-400 uppercase tracking-wider border-b border-zinc-200/80">
              <th className="py-2.5 pr-4">Model</th>
              <th className="py-2.5 pr-4 text-right">Prompt</th>
              <th className="py-2.5 pr-4 text-right">Completion</th>
              <th className="py-2.5 pr-4 text-right">Tổng</th>
              <th className="py-2.5 w-40">Tỉ lệ</th>
            </tr>
          </thead>
          <tbody>
            {items.map(row => {
              const share = totalTokens > 0 ? (row.total_tokens / totalTokens) * 100 : 0
              return (
                <tr key={row.model} className="border-b border-zinc-100 hover:bg-zinc-50/80 transition-colors">
                  <td className="py-2.5 pr-4 font-mono text-xs font-medium text-zinc-900">{row.model}</td>
                  <td className="py-2.5 pr-4 text-right font-mono text-xs text-zinc-600">{fmtTokens(row.prompt_tokens)}</td>
                  <td className="py-2.5 pr-4 text-right font-mono text-xs text-zinc-600">{fmtTokens(row.completion_tokens)}</td>
                  <td className="py-2.5 pr-4 text-right font-mono text-xs font-bold text-zinc-900">{fmtTokens(row.total_tokens)}</td>
                  <td className="py-2.5">
                    <div className="flex items-center gap-2">
                      <div className="flex-1 h-2 bg-zinc-100 rounded-full overflow-hidden">
                        <div
                          className="h-full bg-zinc-900 rounded-full transition-all duration-300"
                          style={{ width: `${share}%` }}
                        />
                      </div>
                      <span className="text-xs font-mono text-zinc-500 w-12 text-right">{share.toFixed(1)}%</span>
                    </div>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}
    </div>
  )
}

// ─── Admin Key gate ──────────────────────────────────────────────────────────

function AdminKeyGate({ onSubmit, error }) {
  const [key, setKey] = useState('')
  return (
    <div className="flex-1 flex items-center justify-center p-6 min-h-[400px]">
      <div className="bg-white border border-zinc-200/90 rounded-2xl shadow-xs w-full max-w-sm p-6">
        <div className="w-10 h-10 bg-zinc-100 border border-zinc-200/80 rounded-xl flex items-center justify-center mb-4">
          <svg className="w-5 h-5 text-zinc-900" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.75}
              d="M15 7a2 2 0 012 2m4 0a6 6 0 01-7.743 5.743L11 17H9v2H7v2H4a1 1 0 01-1-1v-2.586a1 1 0 01.293-.707l5.964-5.964A6 6 0 1121 9z" />
          </svg>
        </div>
        <h2 className="text-base font-bold text-zinc-900">Yêu cầu Admin Key</h2>
        <p className="text-xs text-zinc-500 mt-1">
          Nhập <code className="text-xs font-mono bg-zinc-100 px-1.5 py-0.5 rounded border border-zinc-200/70 text-zinc-800">ADMIN_KEY</code> để xem thống kê gateway.
        </p>
        <form
          className="mt-4 space-y-3"
          onSubmit={e => {
            e.preventDefault()
            if (key.trim()) onSubmit(key.trim())
          }}
        >
          <input
            type="password"
            value={key}
            onChange={e => setKey(e.target.value)}
            placeholder="Nhập admin key…"
            autoFocus
            className={`w-full text-sm font-mono border rounded-xl px-3.5 py-2.5 focus:outline-none focus:ring-2 transition-all ${
              error
                ? 'border-rose-300 focus:ring-rose-100 focus:border-rose-500'
                : 'border-zinc-200 focus:ring-zinc-900/10 focus:border-zinc-900 text-zinc-900'
            }`}
          />
          {error && <p className="text-xs text-rose-600 font-medium">{error}</p>}
          <button
            type="submit"
            className="w-full text-sm font-semibold text-white bg-zinc-900 hover:bg-zinc-800 active:scale-[0.99] transition-all rounded-xl py-2.5 shadow-xs cursor-pointer"
          >
            Mở thống kê
          </button>
        </form>
      </div>
    </div>
  )
}

// ─── Charts ──────────────────────────────────────────────────────────────────

function CustomChartTooltip({ active, payload, label }) {
  if (!active || !payload || !payload.length) return null
  return (
    <div className="bg-white/95 backdrop-blur-sm p-3 rounded-xl border border-zinc-200/90 shadow-md text-xs space-y-1.5 min-w-[150px]">
      <div className="font-bold text-zinc-900 border-b border-zinc-100 pb-1">{label}</div>
      {payload.map((entry, idx) => {
        const isCost =
          entry.dataKey === 'cost_usd' ||
          entry.name === 'cost' ||
          entry.name === 'baseline' ||
          entry.dataKey === 'baseline_premium_cost_usd'
        const valStr = isCost ? fmtUsd(entry.value) : entry.value
        const nameLabel =
          entry.name === 'requests'
            ? 'Requests'
            : entry.name === 'cost'
            ? 'Cost'
            : entry.name === 'baseline'
            ? 'Baseline premium'
            : entry.name
        const indicatorColor = entry.stroke || entry.color || entry.fill || '#18181b'
        return (
          <div key={idx} className="flex items-center justify-between gap-3">
            <span className="flex items-center gap-1.5 text-zinc-500">
              <span className="w-2 h-2 rounded-full" style={{ backgroundColor: indicatorColor }} />
              <span>{nameLabel}:</span>
            </span>
            <span className="font-mono font-semibold text-zinc-900">{valStr}</span>
          </div>
        )
      })}
    </div>
  )
}

function TierChart({ data }) {
  const rows = ['T1', 'T2', 'T3'].map(t => ({
    tier: t,
    requests: data.find(d => d.tier === t)?.requests ?? 0,
    cost_usd: data.find(d => d.tier === t)?.cost_usd ?? 0,
  }))
  return (
    <ResponsiveContainer width="100%" height={240}>
      <BarChart data={rows} margin={{ top: 8, right: 8, left: -16, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#f4f4f5" vertical={false} />
        <XAxis dataKey="tier" tick={{ fontSize: 12, fill: '#71717a' }} axisLine={false} tickLine={false} />
        <YAxis yAxisId="req" allowDecimals={false} tick={{ fontSize: 11, fill: '#a1a1aa' }} axisLine={false} tickLine={false} />
        <YAxis yAxisId="cost" orientation="right" tick={{ fontSize: 11, fill: '#a1a1aa' }} axisLine={false} tickLine={false} />
        <Tooltip content={<CustomChartTooltip />} />
        <Legend formatter={v => (v === 'requests' ? 'Requests' : 'Cost')} />
        <Bar yAxisId="req" dataKey="requests" name="requests" fill="#18181b" radius={[4, 4, 0, 0]} maxBarSize={44} />
        <Bar yAxisId="cost" dataKey="cost_usd" name="cost" fill="#10b981" radius={[4, 4, 0, 0]} maxBarSize={44} />
      </BarChart>
    </ResponsiveContainer>
  )
}

function ProviderChart({ data }) {
  return (
    <ResponsiveContainer width="100%" height={240}>
      <BarChart data={data} layout="vertical" margin={{ top: 8, right: 16, left: 8, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#f4f4f5" horizontal={false} />
        <XAxis type="number" allowDecimals={false} tick={{ fontSize: 11, fill: '#a1a1aa' }} axisLine={false} tickLine={false} />
        <YAxis type="category" dataKey="provider" width={72} tick={{ fontSize: 12, fill: '#71717a' }} axisLine={false} tickLine={false} />
        <Tooltip content={<CustomChartTooltip />} />
        <Legend formatter={v => (v === 'requests' ? 'Requests' : 'Cost')} />
        <Bar dataKey="requests" name="requests" fill="#18181b" radius={[0, 4, 4, 0]} maxBarSize={16} />
        <Bar dataKey="cost_usd" name="cost" fill="#10b981" radius={[0, 4, 4, 0]} maxBarSize={16} />
      </BarChart>
    </ResponsiveContainer>
  )
}

function TimeSeriesChart({ data }) {
  return (
    <ResponsiveContainer width="100%" height={260}>
      <LineChart data={data} margin={{ top: 8, right: 8, left: -16, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#f4f4f5" vertical={false} />
        <XAxis dataKey="date" tick={{ fontSize: 11, fill: '#71717a' }} axisLine={false} tickLine={false} />
        <YAxis yAxisId="req" allowDecimals={false} tick={{ fontSize: 11, fill: '#a1a1aa' }} axisLine={false} tickLine={false} />
        <YAxis yAxisId="cost" orientation="right" tick={{ fontSize: 11, fill: '#a1a1aa' }} axisLine={false} tickLine={false} />
        <Tooltip content={<CustomChartTooltip />} />
        <Legend />
        <Line yAxisId="req" type="monotone" dataKey="requests" name="requests" stroke="#18181b" strokeWidth={2.25} dot={false} />
        <Line yAxisId="cost" type="monotone" dataKey="cost_usd" name="cost" stroke="#10b981" strokeWidth={2.25} dot={false} />
        <Line yAxisId="cost" type="monotone" dataKey="baseline_premium_cost_usd" name="baseline" stroke="#a1a1aa" strokeWidth={1.75} strokeDasharray="5 3" dot={false} />
      </LineChart>
    </ResponsiveContainer>
  )
}

// ─── Logs table ──────────────────────────────────────────────────────────────

function LogsTable({ items }) {
  if (!items.length) {
    return <p className="text-sm text-zinc-400 py-6 text-center">Chưa có request nào trong khoảng thời gian này.</p>
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-xs font-semibold text-zinc-400 uppercase tracking-wider border-b border-zinc-200/80">
            <th className="py-2.5 pr-4">Time</th>
            <th className="py-2.5 pr-4">Request ID</th>
            <th className="py-2.5 pr-4">Tier</th>
            <th className="py-2.5 pr-4">Model</th>
            <th className="py-2.5 pr-4">Provider</th>
            <th className="py-2.5 pr-4 text-right">Cost</th>
            <th className="py-2.5 pr-4 text-right">Latency</th>
            <th className="py-2.5">Status</th>
          </tr>
        </thead>
        <tbody>
          {items.map(row => (
            <tr key={row.request_id} className="border-b border-zinc-100 hover:bg-zinc-50/80 transition-colors">
              <td className="py-2.5 pr-4 whitespace-nowrap text-zinc-500 text-xs">
                {row.ts ? new Date(row.ts).toLocaleString() : '—'}
              </td>
              <td className="py-2.5 pr-4 font-mono text-xs text-zinc-600" title={row.request_id}>
                {row.request_id.slice(0, 8)}…
              </td>
              <td className="py-2.5 pr-4">
                <span className="font-semibold text-xs px-2 py-0.5 rounded-full border border-zinc-200 bg-zinc-100/80 text-zinc-800">
                  {row.tier || '—'}
                </span>
              </td>
              <td className="py-2.5 pr-4 font-mono text-xs text-zinc-900 font-medium">{row.model || '—'}</td>
              <td className="py-2.5 pr-4 text-zinc-500 text-xs">{row.provider || '—'}</td>
              <td className="py-2.5 pr-4 text-right font-mono text-xs text-zinc-900 font-semibold">
                {row.cost_usd == null ? '—' : fmtUsd(row.cost_usd)}
              </td>
              <td className="py-2.5 pr-4 text-right font-mono text-xs text-zinc-600">
                {row.latency_total_ms == null ? '—' : row.latency_total_ms + ' ms'}
              </td>
              <td className="py-2.5"><StatusBadge status={row.status} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ─── Main component ──────────────────────────────────────────────────────────

export default function StatsPage() {
  // TODO(#155): tạm mở khoá — đặt key trong sessionStorage để bật lại gate.
  const [adminKey, setAdminKey] = useState(() => sessionStorage.getItem('sr_admin_key') || 'open-mode')
  const [keyError, setKeyError] = useState(null)
  const [from, setFrom] = useState(sevenDaysAgo)
  const [to, setTo] = useState(isoDay(new Date()))
  const [stats, setStats] = useState(null)
  const [logs, setLogs] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      // to là inclusive ở UI nhưng exclusive ở backend → +1 ngày.
      const toDate = new Date(to + 'T00:00:00Z')
      toDate.setUTCDate(toDate.getUTCDate() + 1)
      const [s, l] = await Promise.all([fetchAdminStats(from, isoDay(toDate)), fetchAdminLogs(from, isoDay(toDate))])
      setStats(s)
      setLogs(l.items)
    } finally {
      setLoading(false)
    }
  }, [from, to])

  useEffect(() => {
    if (!adminKey) return
    load().catch(e => {
      if (e instanceof AdminAuthError) {
        // Gate tắt — chỉ kích hoạt nếu backend thực sự từ chối (ADMIN_KEY được set).
        sessionStorage.removeItem('sr_admin_key')
        setAdminKey(null)
        setKeyError('Admin key không đúng hoặc đã hết hiệu lực.')
      } else {
        setError(e.message)
      }
    })
  }, [load, adminKey])

  const saveKey = k => {
    sessionStorage.setItem('sr_admin_key', k)
    setAdminKey(k)
    setKeyError(null)
  }

  if (!adminKey) {
    return <AdminKeyGate onSubmit={saveKey} error={keyError} />
  }

  const totals = stats?.totals

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Header */}
      <header className="flex flex-col sm:flex-row sm:items-center justify-between px-4 sm:px-6 py-3 sm:py-4 bg-white border-b border-zinc-100 flex-none gap-3">
        <div className="flex items-center gap-2">
          <span className="text-sm font-bold text-zinc-900 tracking-tight">Overview &amp; Metrics</span>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex items-center gap-1.5">
            <label className="text-xs text-zinc-400">From</label>
            <input
              type="date"
              value={from}
              max={to}
              onChange={e => setFrom(e.target.value)}
              className="text-xs border border-zinc-200 rounded-full px-2.5 sm:px-3 py-1.5 text-zinc-700 focus:outline-none focus:ring-1 focus:ring-zinc-400"
            />
          </div>
          <div className="flex items-center gap-1.5">
            <label className="text-xs text-zinc-400">To</label>
            <input
              type="date"
              value={to}
              min={from}
              onChange={e => setTo(e.target.value)}
              className="text-xs border border-zinc-200 rounded-full px-2.5 sm:px-3 py-1.5 text-zinc-700 focus:outline-none focus:ring-1 focus:ring-zinc-400"
            />
          </div>
          <button
            onClick={() => load()}
            disabled={loading}
            className="text-xs font-semibold text-white bg-zinc-900 hover:bg-zinc-800 disabled:opacity-50 transition-colors rounded-full px-3.5 sm:px-4 py-1.5 shadow-xs"
          >
            {loading ? 'Đang tải…' : 'Refresh'}
          </button>
          <button
            onClick={() => {
              sessionStorage.removeItem('sr_admin_key')
              setAdminKey(null)
              setKeyError(null)
            }}
            title="Đổi Admin Key"
            className="p-1.5 text-zinc-500 hover:text-zinc-900 border border-zinc-200 rounded-full transition-colors hover:bg-zinc-50 w-8 h-8 flex items-center justify-center"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M15 7a2 2 0 012 2m4 0a6 6 0 01-7.743 5.743L11 17H9v2H7v2H4a1 1 0 01-1-1v-2.586a1 1 0 01.293-.707l5.964-5.964A6 6 0 1121 9z" />
            </svg>
          </button>
        </div>
      </header>

      {/* Body */}
      <div className="flex-1 overflow-y-auto px-3 sm:px-6 py-4 sm:py-6 space-y-4 sm:space-y-6 touch-scroll">
        {error && (
          <div className="bg-rose-50 border border-rose-200 text-rose-700 text-sm rounded-2xl px-4 py-3 flex items-center justify-between">
            <span>{error}</span>
            <button onClick={() => load()} className="text-xs font-medium underline underline-offset-2">
              Thử lại
            </button>
          </div>
        )}

        {!stats && !error ? (
          <div className="flex items-center justify-center py-20 text-zinc-400">
            <svg className="w-6 h-6 animate-spin" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
          </div>
        ) : (
          <>
            {/* KPI row */}
            <div className="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-6 gap-2.5 sm:gap-3.5">
              <KpiCard label="Requests" value={totals?.requests ?? 0} />
              <KpiCard label="Actual Cost" value={fmtUsd(totals?.cost_usd)} />
              <KpiCard
                label="Baseline Cost"
                value={fmtUsd(totals?.baseline_premium_cost_usd)}
                sub={`nếu dùng ${stats.baseline_model} cho mọi request`}
                title={`Baseline premium model: ${stats.baseline_model}`}
              />
              <KpiCard label="Savings" value={fmtPct(totals?.savings_pct)} accent="text-emerald-600" sub={`vs ${stats.baseline_model}`} />
              <KpiCard label="Avg Latency" value={(totals?.avg_latency_ms ?? 0) + ' ms'} />
              <KpiCard
                label="Success Rate"
                value={((totals?.success_rate ?? 0) * 100).toFixed(1) + '%'}
                accent="text-zinc-900"
              />
            </div>

            {/* Charts */}
            <div className="grid grid-cols-1 xl:grid-cols-2 gap-4 sm:gap-5">
              <ChartCard title="Breakdown theo tier (requests & cost)">
                <TierChart data={stats.by_tier} />
              </ChartCard>
              <ChartCard title="Breakdown theo provider">
                <ProviderChart data={stats.by_provider} />
              </ChartCard>
            </div>

            <ChartCard
              title={
                <span title={`Baseline premium model: ${stats.baseline_model}`}>
                  Requests &amp; cost theo ngày vs{' '}
                  <span className="underline decoration-dotted underline-offset-4 cursor-help">baseline premium</span>
                </span>
              }
            >
              <TimeSeriesChart data={stats.series} />
            </ChartCard>

            <TokenUsagePanel items={stats.tokens_by_model} totalTokens={totals?.total_tokens ?? 0} />

            {/* Logs */}
            <div className="bg-white border border-zinc-200/90 rounded-2xl p-4 sm:p-5 shadow-xs">
              <h3 className="text-sm font-semibold text-zinc-800 mb-4">Request logs gần nhất</h3>
              <LogsTable items={logs} />
            </div>
          </>
        )}
      </div>
    </div>
  )
}
