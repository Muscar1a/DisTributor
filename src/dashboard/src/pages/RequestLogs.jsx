import { useCallback, useEffect, useState } from 'react'
import { AdminAuthError, fetchAdminRequestDetail, fetchAdminRequests } from '../api'

const TIER_CONFIG = {
  T1: { label: 'T1', bg: 'bg-emerald-50 text-emerald-700 border-emerald-200', text: 'text-emerald-600' },
  T2: { label: 'T2', bg: 'bg-amber-50 text-amber-700 border-amber-200', text: 'text-amber-600' },
  T3: { label: 'T3', bg: 'bg-rose-50 text-rose-700 border-rose-200', text: 'text-rose-600' },
}

const STATUS_STYLES = {
  ok: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  error: 'bg-rose-50 text-rose-700 border-rose-200',
  pending: 'bg-amber-50 text-amber-700 border-amber-200',
  incomplete: 'bg-zinc-100 text-zinc-600 border-zinc-200',
}

function fmtUsd(v) {
  if (v == null) return '—'
  return '$' + Number(v).toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 6 })
}

function fmtTokens(v) {
  if (v == null) return '—'
  return Number(v).toLocaleString('en-US')
}

export default function RequestLogs() {
  const [items, setItems] = useState([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(25)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  // Filters
  const [dateRange, setDateRange] = useState('7d') // '24h' | '7d' | '30d' | 'all'
  const [tier, setTier] = useState('')
  const [provider, setProvider] = useState('')
  const [status, setStatus] = useState('')
  const [fallbackOnly, setFallbackOnly] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')

  // Expanded row detail
  const [expandedId, setExpandedId] = useState(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [detailData, setDetailData] = useState({})

  const getDateFilter = useCallback(() => {
    const now = new Date()
    if (dateRange === '24h') {
      const from = new Date(now.getTime() - 24 * 60 * 60 * 1000)
      return { from: from.toISOString(), to: now.toISOString() }
    }
    if (dateRange === '7d') {
      const from = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000)
      return { from: from.toISOString(), to: now.toISOString() }
    }
    if (dateRange === '30d') {
      const from = new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000)
      return { from: from.toISOString(), to: now.toISOString() }
    }
    return {}
  }, [dateRange])

  const loadLogs = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const dateParams = getDateFilter()
      const res = await fetchAdminRequests({
        page,
        pageSize,
        from: dateParams.from,
        to: dateParams.to,
        tier: tier || undefined,
        provider: provider || undefined,
        status: status || undefined,
        minFallback: fallbackOnly ? 1 : undefined,
        q: searchQuery.trim() || undefined,
      })
      setItems(res.items || [])
      setTotal(res.total || 0)
    } catch (err) {
      if (err instanceof AdminAuthError) {
        setError('Admin Key không hợp lệ hoặc chưa được cấu hình.')
      } else {
        setError(err.message || 'Không thể tải danh sách request logs.')
      }
    } finally {
      setLoading(false)
    }
  }, [page, pageSize, getDateFilter, tier, provider, status, fallbackOnly, searchQuery])

  useEffect(() => {
    loadLogs()
  }, [loadLogs])

  const toggleExpand = async id => {
    if (expandedId === id) {
      setExpandedId(null)
      return
    }
    setExpandedId(id)
    if (!detailData[id]) {
      setDetailLoading(true)
      try {
        const detail = await fetchAdminRequestDetail(id)
        setDetailData(prev => ({ ...prev, [id]: detail }))
      } catch (err) {
        console.error('Failed to load detail for request', id, err)
      } finally {
        setDetailLoading(false)
      }
    }
  }

  const totalPages = Math.max(1, Math.ceil(total / pageSize))

  return (
    <div className="flex-1 flex flex-col h-full overflow-hidden bg-white">
      {/* ─── Header & Filter Bar ────────────────────────────────────────────── */}
      <div className="p-3 sm:p-5 md:p-6 border-b border-zinc-100 flex-none space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-lg sm:text-xl font-bold tracking-tight text-zinc-900">Request Logs</h2>
            <p className="text-[11px] sm:text-xs text-zinc-400 mt-0.5">
              Giải thích chi tiết từng quyết định chấm điểm độ khó và lịch sử định tuyến model.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => loadLogs()}
              disabled={loading}
              className="px-3 sm:px-3.5 py-1.5 rounded-full text-xs font-semibold text-zinc-700 bg-zinc-100 hover:bg-zinc-200 transition-colors flex items-center gap-1.5 cursor-pointer disabled:opacity-50"
            >
              <svg
                className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`}
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
                />
              </svg>
              <span>Làm mới</span>
            </button>
          </div>
        </div>

        {/* Filters Row */}
        <div className="flex flex-wrap items-center gap-2 pt-1 text-xs">
          {/* Time range pills */}
          <div className="inline-flex rounded-lg bg-zinc-100 p-0.5 border border-zinc-200/60 overflow-x-auto no-scrollbar">
            {[
              { id: '24h', label: '24h qua' },
              { id: '7d', label: '7 ngày' },
              { id: '30d', label: '30 ngày' },
              { id: 'all', label: 'Tất cả' },
            ].map(r => (
              <button
                key={r.id}
                onClick={() => {
                  setDateRange(r.id)
                  setPage(1)
                }}
                className={`px-2.5 sm:px-3 py-1 rounded-md font-medium transition-all whitespace-nowrap ${
                  dateRange === r.id
                    ? 'bg-white text-zinc-900 font-semibold shadow-xs'
                    : 'text-zinc-500 hover:text-zinc-900'
                }`}
              >
                {r.label}
              </button>
            ))}
          </div>

          {/* Tier select */}
          <select
            value={tier}
            onChange={e => {
              setTier(e.target.value)
              setPage(1)
            }}
            className="px-2.5 sm:px-3 py-1.5 rounded-lg border border-zinc-200 bg-white text-zinc-700 font-medium focus:outline-none focus:ring-1 focus:ring-zinc-400"
          >
            <option value="">Tier: Tất cả</option>
            <option value="T1">T1 (Dễ)</option>
            <option value="T2">T2 (Trung bình)</option>
            <option value="T3">T3 (Khó)</option>
          </select>

          {/* Provider select */}
          <select
            value={provider}
            onChange={e => {
              setProvider(e.target.value)
              setPage(1)
            }}
            className="px-2.5 sm:px-3 py-1.5 rounded-lg border border-zinc-200 bg-white text-zinc-700 font-medium focus:outline-none focus:ring-1 focus:ring-zinc-400"
          >
            <option value="">Provider: Tất cả</option>
            <option value="google">Google</option>
            <option value="groq">Groq</option>
            <option value="openai">OpenAI</option>
            <option value="anthropic">Anthropic</option>
            <option value="mock">Mock</option>
          </select>

          {/* Status select */}
          <select
            value={status}
            onChange={e => {
              setStatus(e.target.value)
              setPage(1)
            }}
            className="px-2.5 sm:px-3 py-1.5 rounded-lg border border-zinc-200 bg-white text-zinc-700 font-medium focus:outline-none focus:ring-1 focus:ring-zinc-400"
          >
            <option value="">Trạng thái: Tất cả</option>
            <option value="ok">Thành công (ok)</option>
            <option value="error">Lỗi (error)</option>
            <option value="pending">Đang xử lý (pending)</option>
            <option value="incomplete">Mồ côi (incomplete)</option>
          </select>

          {/* Fallback only toggle */}
          <button
            onClick={() => {
              setFallbackOnly(!fallbackOnly)
              setPage(1)
            }}
            className={`px-2.5 sm:px-3 py-1.5 rounded-lg border text-xs font-semibold transition-colors whitespace-nowrap ${
              fallbackOnly
                ? 'bg-rose-50 border-rose-300 text-rose-700 shadow-xs'
                : 'bg-white border-zinc-200 text-zinc-600 hover:bg-zinc-50'
            }`}
          >
            ⚠️ Chỉ có Fallback
          </button>

          {/* Search by Request ID */}
          <div className="flex-1 min-w-[160px] sm:min-w-[200px] relative">
            <input
              type="text"
              value={searchQuery}
              onChange={e => {
                setSearchQuery(e.target.value)
                setPage(1)
              }}
              placeholder="Tìm theo Request ID..."
              className="w-full pl-8 pr-3 py-1.5 rounded-lg border border-zinc-200 text-xs text-zinc-800 placeholder-zinc-400 focus:outline-none focus:ring-1 focus:ring-zinc-400"
            />
            <svg
              className="w-3.5 h-3.5 text-zinc-400 absolute left-2.5 top-2.5"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
          </div>
        </div>
      </div>

      {/* ─── Main Content Table ─────────────────────────────────────────────── */}
      <div className="flex-1 overflow-auto min-h-0 touch-scroll">
        {error ? (
          <div className="p-8 text-center">
            <div className="inline-flex p-3 rounded-full bg-rose-50 text-rose-600 mb-3 border border-rose-100">
              <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
              </svg>
            </div>
            <p className="text-sm font-semibold text-zinc-800">{error}</p>
          </div>
        ) : loading && items.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-24 text-zinc-400">
            <svg className="w-8 h-8 animate-spin text-zinc-500 mb-3" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
            <span className="text-xs font-medium">Đang tải dữ liệu request logs...</span>
          </div>
        ) : items.length === 0 ? (
          <div className="text-center py-20 text-zinc-400">
            <svg className="w-12 h-12 mx-auto text-zinc-300 mb-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
            </svg>
            <p className="text-sm font-medium text-zinc-600">Không tìm thấy request nào</p>
            <p className="text-xs text-zinc-400 mt-1">Thử thay đổi bộ lọc hoặc thời gian tìm kiếm.</p>
          </div>
        ) : (
          <table className="w-full min-w-[760px] text-left text-xs border-collapse">
            <thead className="bg-zinc-50 sticky top-0 border-b border-zinc-200 z-10 select-none">
              <tr className="text-zinc-500 font-semibold uppercase tracking-wider text-[11px]">
                <th className="py-3 px-4 w-8" />
                <th className="py-3 px-3">Thời gian</th>
                <th className="py-3 px-3 text-center">Score</th>
                <th className="py-3 px-3">Tier</th>
                <th className="py-3 px-3">Model @ Provider</th>
                <th className="py-3 px-3 text-right">Tokens (In / Out)</th>
                <th className="py-3 px-3 text-right">Cost</th>
                <th className="py-3 px-3 text-right">Latency</th>
                <th className="py-3 px-3 text-center" title="Số lần Fallback">FB</th>
                <th className="py-3 px-4">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-100">
              {items.map(row => {
                const isExpanded = expandedId === row.id
                const tierCfg = TIER_CONFIG[row.tier] || { label: row.tier || '—', bg: 'bg-zinc-100 text-zinc-600 border-zinc-200' }
                const statusStyle = STATUS_STYLES[row.status] || STATUS_STYLES.incomplete
                const detail = detailData[row.id]

                return (
                  <tr
                    key={row.id}
                    className={`transition-colors hover:bg-zinc-50/80 ${isExpanded ? 'bg-zinc-50/60' : ''}`}
                  >
                    <td colSpan={10} className="p-0">
                      {/* Main Row */}
                      <div
                        onClick={() => toggleExpand(row.id)}
                        className="flex items-center py-3.5 px-0 cursor-pointer select-none"
                      >
                        {/* Expand Icon */}
                        <div className="w-8 flex-none flex items-center justify-center text-zinc-400 hover:text-zinc-800">
                          <svg
                            className={`w-3.5 h-3.5 transition-transform duration-200 ${isExpanded ? 'rotate-90 text-zinc-800' : ''}`}
                            fill="none"
                            stroke="currentColor"
                            viewBox="0 0 24 24"
                          >
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                          </svg>
                        </div>

                        {/* Time */}
                        <div className="px-3 flex-1 min-w-[130px] font-mono text-zinc-600">
                          {row.ts ? (
                            <div>
                              <div className="font-semibold text-zinc-800">
                                {new Date(row.ts).toLocaleTimeString('vi-VN')}
                              </div>
                              <div className="text-[10px] text-zinc-400">
                                {new Date(row.ts).toLocaleDateString('vi-VN')}
                              </div>
                            </div>
                          ) : (
                            '—'
                          )}
                        </div>

                        {/* Score */}
                        <div className="px-3 w-16 text-center font-mono font-bold text-zinc-800">
                          {row.difficulty_score ?? '—'}
                        </div>

                        {/* Tier */}
                        <div className="px-3 w-16 flex-none">
                          <span className={`inline-flex items-center justify-center px-2 py-0.5 rounded-full font-bold text-[11px] border ${tierCfg.bg}`}>
                            {tierCfg.label}
                          </span>
                        </div>

                        {/* Model @ Provider */}
                        <div className="px-3 flex-[2] min-w-[180px]">
                          <div className="font-mono text-xs font-semibold text-zinc-800">
                            {row.model || 'auto'}
                          </div>
                          <div className="text-[10px] text-zinc-400 uppercase tracking-wider font-semibold">
                            @{row.provider || 'unknown'} {row.stream ? '· stream' : ''}
                          </div>
                        </div>

                        {/* Tokens */}
                        <div className="px-3 flex-1 min-w-[120px] text-right font-mono text-zinc-600">
                          <div>{fmtTokens((row.prompt_tokens || 0) + (row.completion_tokens || 0))}</div>
                          <div className="text-[10px] text-zinc-400">
                            {fmtTokens(row.prompt_tokens)} / {fmtTokens(row.completion_tokens)}
                          </div>
                        </div>

                        {/* Cost */}
                        <div className="px-3 flex-1 min-w-[90px] text-right font-mono font-semibold text-zinc-800">
                          {fmtUsd(row.cost_usd)}
                        </div>

                        {/* Latency */}
                        <div className="px-3 flex-1 min-w-[100px] text-right font-mono text-zinc-600">
                          <div>{row.latency_total_ms != null ? `${row.latency_total_ms}ms` : '—'}</div>
                          {row.latency_router_ms != null && (
                            <div className="text-[10px] text-zinc-400">
                              router: {row.latency_router_ms}ms
                            </div>
                          )}
                        </div>

                        {/* Fallback count */}
                        <div className="px-3 w-12 text-center font-mono font-bold">
                          {row.fallback_count > 0 ? (
                            <span className="text-rose-600 font-extrabold bg-rose-50 px-1.5 py-0.5 rounded border border-rose-200">
                              {row.fallback_count}
                            </span>
                          ) : (
                            <span className="text-zinc-400">0</span>
                          )}
                        </div>

                        {/* Status */}
                        <div className="px-4 w-24 flex-none">
                          <span className={`inline-flex items-center px-2 py-0.5 rounded-full font-semibold text-[10px] border uppercase ${statusStyle}`}>
                            {row.status}
                          </span>
                        </div>
                      </div>

                      {/* Expanded Details Drawer */}
                      {isExpanded && (
                        <div className="px-6 py-4 bg-zinc-50 border-t border-b border-zinc-200/80 space-y-4">
                          {detailLoading && !detail ? (
                            <div className="flex items-center gap-2 text-zinc-400 py-2">
                              <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                              </svg>
                              <span>Đang tải thông tin chi tiết giải trình...</span>
                            </div>
                          ) : (
                            <>
                              {/* Metadata chips */}
                              <div className="grid grid-cols-1 md:grid-cols-4 gap-3 text-xs">
                                <div className="p-3 bg-white rounded-xl border border-zinc-200/80 shadow-2xs">
                                  <div className="text-[10px] font-bold text-zinc-400 uppercase tracking-wider">Request ID</div>
                                  <div className="font-mono text-xs text-zinc-800 mt-1 select-all break-all">{row.id}</div>
                                </div>

                                <div className="p-3 bg-white rounded-xl border border-zinc-200/80 shadow-2xs">
                                  <div className="text-[10px] font-bold text-zinc-400 uppercase tracking-wider">Routing Policy &amp; Version</div>
                                  <div className="text-xs font-semibold text-zinc-800 mt-1">
                                    {row.policy || 'default'} · <span className="font-mono text-zinc-500">{detail?.classifier_version || 'v1'}</span>
                                  </div>
                                </div>

                                <div className="p-3 bg-white rounded-xl border border-zinc-200/80 shadow-2xs">
                                  <div className="text-[10px] font-bold text-zinc-400 uppercase tracking-wider">Router Cost &amp; Overhead</div>
                                  <div className="text-xs font-semibold text-zinc-800 mt-1 font-mono">
                                    {fmtUsd(detail?.router_cost_usd || 0)} · {row.latency_router_ms ?? 0}ms
                                  </div>
                                </div>

                                <div className="p-3 bg-white rounded-xl border border-zinc-200/80 shadow-2xs">
                                  <div className="text-[10px] font-bold text-zinc-400 uppercase tracking-wider">API Key / Session</div>
                                  <div className="text-xs font-medium text-zinc-700 mt-1 truncate">
                                    {row.api_key_name ? `Key: ${row.api_key_name}` : 'Default Key'}
                                    {detail?.session_id && <span className="block font-mono text-[10px] text-zinc-400 truncate">Ses: {detail.session_id}</span>}
                                  </div>
                                </div>
                              </div>

                              {/* Signals breakdown */}
                              <div className="p-3 bg-white rounded-xl border border-zinc-200/80 shadow-2xs space-y-2">
                                <div className="text-[11px] font-bold text-zinc-700 uppercase tracking-wider flex items-center justify-between">
                                  <span>Tín hiệu chấm điểm độ khó (Signals Breakdown)</span>
                                  <span className="font-mono text-xs text-zinc-500 font-bold">Tổng điểm: {row.difficulty_score ?? 0}/100</span>
                                </div>

                                {detail?.signals && detail.signals.length > 0 ? (
                                  <div className="flex flex-wrap gap-2 pt-1">
                                    {detail.signals.map((sig, idx) => (
                                      <span
                                        key={idx}
                                        className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-zinc-100 text-zinc-800 text-xs font-mono border border-zinc-200"
                                      >
                                        <span className="font-semibold text-zinc-900">{sig.name || sig.signal || JSON.stringify(sig)}</span>
                                        {sig.points != null && (
                                          <span className="text-orange-600 font-bold">+{sig.points}</span>
                                        )}
                                        {sig.score != null && sig.points == null && (
                                          <span className="text-orange-600 font-bold">{sig.score}</span>
                                        )}
                                      </span>
                                    ))}
                                  </div>
                                ) : (
                                  <p className="text-xs text-zinc-400 italic">Không có tín hiệu đặc biệt (request dạng standard text).</p>
                                )}
                              </div>

                              {/* Chain attempted */}
                              {detail?.chain_attempted && detail.chain_attempted.length > 0 && (
                                <div className="p-3 bg-white rounded-xl border border-zinc-200/80 shadow-2xs space-y-2">
                                  <div className="text-[11px] font-bold text-zinc-700 uppercase tracking-wider">
                                    Chuỗi model đã thử (Chain Attempted)
                                  </div>
                                  <div className="space-y-1.5">
                                    {detail.chain_attempted.map((step, idx) => (
                                      <div
                                        key={idx}
                                        className="flex items-center justify-between text-xs font-mono p-2 rounded-lg bg-zinc-50 border border-zinc-100"
                                      >
                                        <div className="flex items-center gap-2">
                                          <span className="w-5 h-5 rounded-full bg-zinc-200 text-zinc-700 flex items-center justify-center text-[10px] font-bold">
                                            {idx + 1}
                                          </span>
                                          <span className="font-semibold text-zinc-800">{step.model}</span>
                                          <span className="text-zinc-400">@{step.provider}</span>
                                        </div>
                                        <div className="flex items-center gap-2">
                                          {step.status === 'ok' ? (
                                            <span className="text-emerald-600 font-bold text-[11px]">✓ Thành công</span>
                                          ) : (
                                            <span className="text-rose-600 font-bold text-[11px]">✗ Thất bại ({step.error || 'Lỗi'})</span>
                                          )}
                                        </div>
                                      </div>
                                    ))}
                                  </div>
                                </div>
                              )}

                              {/* Feedback (if any) */}
                              {detail?.feedback && (
                                <div className="p-3 bg-white rounded-xl border border-emerald-200/80 bg-emerald-50/20 space-y-1 text-xs">
                                  <div className="font-bold text-emerald-800 text-[11px] uppercase tracking-wider flex items-center gap-1.5">
                                    <span>✨ Đánh giá chất lượng từ người dùng</span>
                                  </div>
                                  <div className="flex flex-wrap gap-1.5 mt-1">
                                    {detail.feedback.tags?.map((t, i) => (
                                      <span key={i} className="px-2 py-0.5 rounded bg-emerald-100 text-emerald-800 text-[11px] font-semibold">
                                        {t}
                                      </span>
                                    ))}
                                  </div>
                                  {detail.feedback.note && (
                                    <p className="text-zinc-600 italic mt-1">"{detail.feedback.note}"</p>
                                  )}
                                </div>
                              )}

                              {/* Previews (if any) */}
                              {(detail?.prompt_preview || detail?.response_preview) && (
                                <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
                                  {detail.prompt_preview && (
                                    <div className="p-3 bg-white rounded-xl border border-zinc-200/80 shadow-2xs space-y-1">
                                      <div className="text-[10px] font-bold text-zinc-400 uppercase tracking-wider">Prompt Preview</div>
                                      <div className="font-mono text-zinc-700 whitespace-pre-wrap max-h-28 overflow-y-auto text-[11px] bg-zinc-50 p-2 rounded border border-zinc-100">
                                        {detail.prompt_preview}
                                      </div>
                                    </div>
                                  )}
                                  {detail.response_preview && (
                                    <div className="p-3 bg-white rounded-xl border border-zinc-200/80 shadow-2xs space-y-1">
                                      <div className="text-[10px] font-bold text-zinc-400 uppercase tracking-wider">Response Preview</div>
                                      <div className="font-mono text-zinc-700 whitespace-pre-wrap max-h-28 overflow-y-auto text-[11px] bg-zinc-50 p-2 rounded border border-zinc-100">
                                        {detail.response_preview}
                                      </div>
                                    </div>
                                  )}
                                </div>
                              )}
                            </>
                          )}
                        </div>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </div>

      {/* ─── Pagination Footer ──────────────────────────────────────────────── */}
      <div className="p-4 border-t border-zinc-200/80 flex-none flex flex-wrap items-center justify-between gap-3 text-xs text-zinc-500 bg-zinc-50/50">
        <div className="flex items-center gap-2">
          <span>Hiển thị</span>
          <select
            value={pageSize}
            onChange={e => {
              setPageSize(Number(e.target.value))
              setPage(1)
            }}
            className="px-2 py-1 bg-white border border-zinc-200 rounded text-xs font-semibold focus:outline-none"
          >
            <option value={10}>10</option>
            <option value={25}>25</option>
            <option value={50}>50</option>
            <option value={100}>100</option>
          </select>
          <span>/ trang · Tổng <strong className="text-zinc-800">{total}</strong> requests</span>
        </div>

        <div className="flex items-center gap-1.5">
          <button
            onClick={() => setPage(p => Math.max(1, p - 1))}
            disabled={page <= 1 || loading}
            className="px-3 py-1.5 rounded-lg border border-zinc-200 bg-white font-medium hover:bg-zinc-100 disabled:opacity-40 transition-colors"
          >
            ‹ Trước
          </button>
          <span className="px-3 py-1 font-semibold text-zinc-800">
            {page} / {totalPages}
          </span>
          <button
            onClick={() => setPage(p => Math.min(totalPages, p + 1))}
            disabled={page >= totalPages || loading}
            className="px-3 py-1.5 rounded-lg border border-zinc-200 bg-white font-medium hover:bg-zinc-100 disabled:opacity-40 transition-colors"
          >
            Sau ›
          </button>
        </div>
      </div>
    </div>
  )
}
