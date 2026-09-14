import { useState, useRef, useEffect, useCallback, memo } from 'react'
import { createPortal } from 'react-dom'
import ReactMarkdown from 'react-markdown'
import remarkMath from 'remark-math'
import remarkGfm from 'remark-gfm'
import rehypeKatex from 'rehype-katex'
import 'katex/dist/katex.min.css'
import {
  checkHealth,
  sendChatStream,
  fetchUsage,
  sendFeedback,
  createSession,
  sendSessionFeedback,
  fetchSessions,
  fetchSessionHistory,
} from '../api'
import { formatPlaygroundError } from '../api-error'

// ─── Minimal Icons (Origin Style) ───────────────────────────────────────────

const SparkleIcon = ({ className = 'w-4 h-4' }) => (
  <svg className={className} fill="none" stroke="currentColor" viewBox="0 0 24 24">
    <path
      strokeLinecap="round"
      strokeLinejoin="round"
      strokeWidth={1.75}
      d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09zM18.259 8.715L18 9.75l-.259-1.035a3.375 3.375 0 00-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 002.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 002.456 2.456L21.75 6l-1.035.259a3.375 3.375 0 00-2.456 2.456z"
    />
  </svg>
)

const OriginAiAvatar = () => (
  <div className="w-5 h-5 rounded-md border-2 border-zinc-900 flex items-center justify-center flex-shrink-0 mt-0.5">
    <div className="w-1.5 h-1.5 bg-zinc-900 rounded-xs" />
  </div>
)

const PlanAiIcon = () => (
  <svg className="w-4 h-4 text-zinc-800" fill="none" stroke="currentColor" viewBox="0 0 24 24">
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.75} d="M3.75 6A2.25 2.25 0 016 3.75h2.25A2.25 2.25 0 0110.5 6v2.25a2.25 2.25 0 01-2.25 2.25H6a2.25 2.25 0 01-2.25-2.25V6zM3.75 15.75A2.25 2.25 0 016 13.5h2.25a2.25 2.25 0 012.25 2.25V18a2.25 2.25 0 01-2.25 2.25H6A2.25 2.25 0 013.75 18v-2.25zM13.5 6a2.25 2.25 0 012.25-2.25H18A2.25 2.25 0 0120.25 6v2.25A2.25 2.25 0 0118 10.5h-2.25a2.25 2.25 0 01-2.25-2.25V6zM13.5 15.75a2.25 2.25 0 012.25-2.25H18a2.25 2.25 0 012.25 2.25V18A2.25 2.25 0 0118 20.25h-2.25A2.25 2.25 0 0113.5 18v-2.25z" />
  </svg>
)

const ChevronRight = () => (
  <svg className="w-3.5 h-3.5 text-zinc-400 group-hover:text-zinc-700 transition-colors" fill="none" stroke="currentColor" viewBox="0 0 24 24">
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
  </svg>
)

const ChevronDown = () => (
  <svg className="w-3 h-3 text-zinc-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
  </svg>
)

const ThreeDotsIcon = () => (
  <svg className="w-4 h-4 text-zinc-400 hover:text-zinc-800 transition-colors" fill="none" stroke="currentColor" viewBox="0 0 24 24">
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 12h.01M12 12h.01M19 12h.01" />
  </svg>
)

const UpArrowIcon = () => (
  <svg className="w-4 h-4 stroke-[2.25]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
    <path strokeLinecap="round" strokeLinejoin="round" d="M12 19.5v-15m0 0l-6 6m6-6l6 6" />
  </svg>
)

const ThumbsUpIcon = () => (
  <svg className="w-3.5 h-3.5 stroke-[1.5]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
    <path strokeLinecap="round" strokeLinejoin="round" d="M6.633 10.5c.806 0 1.533-.446 2.031-1.08a9.041 9.041 0 012.861-2.4c.723-.384 1.35-.956 1.653-1.715a4.498 4.498 0 00.322-1.672V3a.75.75 0 01.75-.75A2.25 2.25 0 0116.5 4.5c0 1.152-.26 2.243-.723 3.218-.266.558.107 1.282.725 1.282h3.126c1.026 0 1.945.694 2.054 1.715.045.422.068.85.068 1.285a11.95 11.95 0 01-2.649 7.521c-.388.482-.987.729-1.605.729H13.48c-.483 0-.964-.078-1.423-.23l-3.114-1.04a4.501 4.501 0 00-1.423-.23H5.25M6.633 10.5V20.25m0-9.75H3.75A1.5 1.5 0 002.25 12v6.75a1.5 1.5 0 001.5 1.5h2.883" />
  </svg>
)

const ThumbsDownIcon = () => (
  <svg className="w-3.5 h-3.5 stroke-[1.5]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
    <path strokeLinecap="round" strokeLinejoin="round" d="M7.5 13.5h-.883a1.5 1.5 0 01-1.5-1.5V5.25a1.5 1.5 0 011.5-1.5h2.883m0 9.75c.806 0 1.533.446 2.031 1.08a9.041 9.041 0 002.861 2.4c.723.384 1.35.956 1.653 1.715a4.498 4.498 0 01.322 1.672V21a.75.75 0 00.75.75A2.25 2.25 0 0016.5 19.5c0-1.152-.26-2.243-.723-3.218-.266-.558.107-1.282.725-1.282h3.126c1.026 0 1.945-.694 2.054-1.715.045-.422.068-.85.068-1.285a11.95 11.95 0 00-2.649-7.521c-.388-.482-.987-.729-1.605-.729H13.48c-.483 0-.964.078-1.423.23l-3.114 1.04a4.501 4.501 0 01-1.423.23H7.5" />
  </svg>
)

const CopyIcon = () => (
  <svg className="w-3.5 h-3.5 stroke-[1.5]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
    <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 17.25v3.375c0 .621-.504 1.125-1.125 1.125h-9.75a1.125 1.125 0 01-1.125-1.125V7.875c0-.621.504-1.125 1.125-1.125H6.75a9.06 9.06 0 011.5.124m7.5 10.376h3.375c.621 0 1.125-.504 1.125-1.125V11.25c0-4.46-3.243-8.161-7.5-8.876a9.06 9.06 0 00-1.5-.124H9.375c-.621 0-1.125.504-1.125 1.125v3.5m7.5 10.375H9.375a1.125 1.125 0 01-1.125-1.125v-9.25m12 6.625v-1.875a3.375 3.375 0 00-3.375-3.375h-1.5a1.125 1.125 0 01-1.125-1.125v-1.5a3.375 3.375 0 00-3.375-3.375H9.75" />
  </svg>
)

// ─── Routing Signal Meta & Helpers ──────────────────────────────────────────

const TIER_LABEL = { T1: 'Easy', T2: 'Medium', T3: 'Hard' }
const TIER_COLOR = {
  T1: 'bg-zinc-100/90 text-zinc-600 border-zinc-200/80',
  T2: 'bg-zinc-100/90 text-zinc-600 border-zinc-200/80',
  T3: 'bg-zinc-100/90 text-zinc-700 border-zinc-200/80 font-semibold',
}

const SIGNAL_META = {
  band_c1: { label: 'C1: Cơ bản', type: 'band', defaultPoints: 8 },
  band_c2: { label: 'C2: Trung bình', type: 'band', defaultPoints: 32 },
  band_c3: { label: 'C3: Chuyên sâu', type: 'band', defaultPoints: 62 },
  genre_cp: { label: 'Competitive Programming', type: 'band', defaultPoints: 0 },
  error_artifact: { label: 'Lỗi / Stack Trace', type: 'modifier', defaultPoints: 8 },
  artifact_large: { label: 'Code artifact >150 tok', type: 'modifier', defaultPoints: 6 },
  multi_file: { label: 'Nhiều file / Codebase', type: 'modifier', defaultPoints: 6 },
  output_constraint: { label: 'Ràng buộc định dạng', type: 'modifier', defaultPoints: 6 },
  multi_step: { label: 'Suy luận nhiều bước', type: 'modifier', defaultPoints: 6 },
  long_context: { label: 'Ngữ cảnh >2k tok', type: 'modifier', defaultPoints: 6 },
  math: { label: 'Toán học & Logic', type: 'modifier', defaultPoints: 20 },
  long_creative: { label: 'Nội dung dài', type: 'modifier', defaultPoints: 15 },
  length: { label: 'Độ dài câu lệnh', type: 'modifier', defaultPoints: 10 },
  fast_path_easy: { label: 'Fast-path Easy', type: 'state', defaultPoints: 0 },
  failure_boost: { label: 'Boost sửa lỗi', type: 'boost', defaultPoints: 15 },
  ema_inherit: { label: 'Kế thừa độ khó', type: 'boost', defaultPoints: 0 },
}

function SignalBadge({ signal }) {
  const meta = SIGNAL_META[signal.name] || {}
  const label = meta.label || signal.name
  const pts = Number(signal.points || 0)

  return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-zinc-100 text-zinc-700 text-[11px] font-medium border border-zinc-200/80">
      <span>{label}</span>
      {pts > 0 && <span className="font-bold text-zinc-900">+{pts}</span>}
    </span>
  )
}

function mapRouting(sr) {
  const latencyMs = sr.latency_total_ms
  const routerMs  = sr.latency_router_ms
  const activatedSignals = Array.isArray(sr.signals) ? sr.signals : []
  const isFastPath = activatedSignals.length === 0
    || activatedSignals.some(signal => signal.name === 'fast_path_easy')
  const latencyLabel = latencyMs != null
    ? `${(latencyMs / 1000).toFixed(1)}s${routerMs != null ? ` (router ${routerMs}ms)` : ''}`
    : '—'
  const reason = isFastPath
    ? 'Fast-path Easy: Câu lệnh ngắn hoặc tổng quan → định tuyến T1'
    : `Kích hoạt ${activatedSignals.map(signal => SIGNAL_META[signal.name]?.label || signal.name).join(', ')} → định tuyến ${sr.tier}`

  const costVal = sr.cost_usd != null ? `$${Number(sr.cost_usd).toFixed(5)}` : '—'
  const diffScore = sr.difficulty_score ?? sr.difficultyScore ?? 0
  const modelName = sr.model_used || sr.model || 'Unknown'
  const provider = sr.provider || ''

  return {
    requestId: sr.request_id || sr.requestId,
    count: activatedSignals.length,
    tierCode: sr.tier,
    difficulty: TIER_LABEL[sr.tier] ?? sr.tier,
    difficultyScore: diffScore,
    modelName,
    provider,
    activatedSignals,
    reason,
    routerLatencyMs: routerMs,
    costVal,
    latencyLabel,
  }
}

function ScoreBreakdownCard({ routing }) {
  if (!routing) return null
  const score = routing.difficultyScore ?? 0
  const tier = routing.tierCode || 'T1'
  const signals = Array.isArray(routing.activatedSignals) ? routing.activatedSignals : []
  const scorePercent = Math.min(100, Math.max(0, score))

  return (
    <div className="mt-3 p-4 rounded-2xl bg-zinc-50 border border-zinc-200/90 text-xs text-zinc-700 shadow-2xs space-y-3">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-orange-500 animate-pulse" />
          <span className="font-bold text-zinc-900 text-xs tracking-tight">Chi tiết tính điểm &amp; Routing SmartRoute</span>
        </div>
        <span className="font-mono text-[11px] text-zinc-400">ID: {routing.requestId ? `${routing.requestId.slice(0, 8)}…` : '—'}</span>
      </div>

      {/* Visual Score Bar */}
      <div className="p-3 bg-white rounded-xl border border-zinc-200/70 space-y-2">
        <div className="flex items-center justify-between text-[11px]">
          <span className="text-zinc-500 font-medium">Điểm độ khó tổng hợp:</span>
          <span className="font-mono font-extrabold text-sm text-zinc-900">{score} <span className="text-[10px] text-zinc-400 font-normal">/ 100</span></span>
        </div>

        {/* Progress bar with Tier zones */}
        <div className="relative h-2.5 bg-zinc-100 rounded-full overflow-hidden flex">
          <div className="w-[30%] bg-emerald-100/80 border-r border-white/60" title="T1 Zone (<30)" />
          <div className="w-[30%] bg-amber-100/80 border-r border-white/60" title="T2 Zone (30-60)" />
          <div className="w-[40%] bg-rose-100/80" title="T3 Zone (>60)" />

          <div
            className="absolute top-0 bottom-0 w-1.5 bg-zinc-900 rounded-full shadow-xs transition-all duration-500 -ml-0.75"
            style={{ left: `${scorePercent}%` }}
          />
        </div>

        <div className="flex justify-between text-[10px] text-zinc-400 font-mono pt-0.5">
          <span>0 (Dễ - T1)</span>
          <span className="text-zinc-500 font-semibold">30 (Ngưỡng T2)</span>
          <span className="text-zinc-500 font-semibold">60 (Ngưỡng T3)</span>
          <span>100 (Khó)</span>
        </div>
      </div>

      {/* Signals Breakdown */}
      <div className="space-y-1.5">
        <div className="text-[11px] font-bold text-zinc-700 uppercase tracking-wider">
          Các tín hiệu đóng góp điểm (Signals Breakdown)
        </div>
        {signals.length > 0 ? (
          <div className="flex flex-wrap gap-1.5 pt-0.5">
            {signals.map((sig, idx) => {
              const meta = SIGNAL_META[sig.name] || {}
              const label = meta.label || sig.name
              const pts = Number(sig.points || sig.score || 0)
              return (
                <div
                  key={idx}
                  className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-white border border-zinc-200/90 text-zinc-800 text-[11px] shadow-2xs font-mono"
                >
                  <span className="font-semibold">{label}</span>
                  {pts > 0 ? (
                    <span className="font-bold text-orange-600">+{pts} pts</span>
                  ) : pts < 0 ? (
                    <span className="font-bold text-emerald-600">{pts} pts</span>
                  ) : (
                    <span className="text-zinc-400">active</span>
                  )}
                </div>
              )
            })}
          </div>
        ) : (
          <p className="text-[11px] text-zinc-400 italic bg-white p-2.5 rounded-xl border border-zinc-200/60">
            Fast-path standard prompt: Không kích hoạt tín hiệu phức tạp nào.
          </p>
        )}
      </div>

      {/* Decision Summary */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 pt-1">
        <div className="p-2.5 bg-white rounded-xl border border-zinc-200/70">
          <div className="text-[9px] font-bold text-zinc-400 uppercase tracking-wider">Phân hạng Tier</div>
          <div className="text-xs font-bold text-zinc-900 mt-0.5">{tier} ({TIER_LABEL[tier] || tier})</div>
        </div>
        <div className="p-2.5 bg-white rounded-xl border border-zinc-200/70">
          <div className="text-[9px] font-bold text-zinc-400 uppercase tracking-wider">Model đã gọi</div>
          <div className="text-xs font-mono font-semibold text-zinc-900 mt-0.5 truncate">{routing.modelName}</div>
        </div>
        <div className="p-2.5 bg-white rounded-xl border border-zinc-200/70">
          <div className="text-[9px] font-bold text-zinc-400 uppercase tracking-wider">Độ trễ Router</div>
          <div className="text-xs font-mono font-semibold text-zinc-900 mt-0.5">{routing.routerLatencyMs != null ? `${routing.routerLatencyMs}ms` : '—'}</div>
        </div>
        <div className="p-2.5 bg-white rounded-xl border border-zinc-200/70">
          <div className="text-[9px] font-bold text-zinc-400 uppercase tracking-wider">Chi phí ước tính</div>
          <div className="text-xs font-mono font-semibold text-zinc-900 mt-0.5">{routing.costVal}</div>
        </div>
      </div>
    </div>
  )
}

// ─── Session Feedback Modal ─────────────────────────────────────────────────

const SESSION_FEEDBACK_TAGS = [
  { id: 'good_routing', label: 'Routing tốt, tiết kiệm chi phí', icon: '⚡' },
  { id: 'inconsistent', label: 'Routing không nhất quán', icon: '⚠️' },
  { id: 'need_stronger', label: 'Nên dùng model mạnh hơn', icon: '🚀' },
  { id: 'need_smaller', label: 'Nên dùng model nhỏ hơn', icon: '💡' },
  { id: 'other', label: 'Khác', icon: '💬' },
]

function SessionFeedbackModal({ isOpen, onClose, sessionId }) {
  const [selectedTags, setSelectedTags] = useState([])
  const [note, setNote] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState(null)
  const [success, setSuccess] = useState(false)

  useEffect(() => {
    if (isOpen) {
      setSelectedTags([])
      setNote('')
      setError(null)
      setSuccess(false)
    }
  }, [isOpen])

  if (!isOpen) return null

  const toggleTag = (tagLabel) => {
    setSelectedTags(prev =>
      prev.includes(tagLabel)
        ? prev.filter(t => t !== tagLabel)
        : [...prev, tagLabel]
    )
  }

  const handleSubmit = async (e) => {
    e?.preventDefault()
    if (!sessionId) {
      setError('Chưa có phiên hội thoại nào đang diễn ra.')
      return
    }
    if (selectedTags.length === 0 && !note.trim()) {
      setError('Vui lòng chọn ít nhất 1 tiêu chí hoặc nhập ghi chú.')
      return
    }

    setSubmitting(true)
    setError(null)

    try {
      await sendSessionFeedback(sessionId, selectedTags, note.trim())
      setSuccess(true)
      setTimeout(() => {
        onClose()
      }, 1400)
    } catch (err) {
      if (err.message?.includes('409') || err.message?.includes('already exists')) {
        setError('Phiên hội thoại này đã được gửi phản hồi trước đó.')
      } else {
        setError(err.message || 'Không thể gửi phản hồi. Vui lòng thử lại.')
      }
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-zinc-950/40 backdrop-blur-xs select-none animate-fadeIn">
      <div className="bg-white rounded-3xl border border-zinc-200/90 shadow-2xl w-full max-w-lg overflow-hidden flex flex-col">
        {/* Modal Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-zinc-100 bg-zinc-50/60">
          <div className="flex items-center gap-2.5">
            <span className="w-8 h-8 rounded-xl bg-zinc-900 text-white flex items-center justify-center text-xs shadow-xs">
              ✨
            </span>
            <div>
              <h3 className="text-sm font-bold text-zinc-900">Phản hồi chất lượng phiên hội thoại</h3>
              <p className="text-[11px] text-zinc-400 font-mono truncate max-w-[280px]">
                {sessionId ? `Session: ${sessionId.slice(0, 8)}…` : 'Chưa có session'}
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="w-7 h-7 rounded-full flex items-center justify-center text-zinc-400 hover:text-zinc-800 hover:bg-zinc-100 transition-colors cursor-pointer text-sm font-bold"
          >
            ✕
          </button>
        </div>

        {/* Modal Body */}
        <div className="p-6 space-y-5">
          {success ? (
            <div className="py-6 text-center space-y-2">
              <div className="w-12 h-12 rounded-full bg-emerald-100 text-emerald-600 flex items-center justify-center text-xl mx-auto font-bold">
                ✓
              </div>
              <h4 className="text-sm font-bold text-zinc-900">Đã gửi phản hồi thành công!</h4>
              <p className="text-xs text-zinc-500">Cảm ơn Bun đã đánh giá. Dữ liệu này giúp bộ định tuyến tối ưu độ chính xác và chi phí.</p>
            </div>
          ) : !sessionId ? (
            <div className="py-6 text-center space-y-3">
              <p className="text-xs text-zinc-500">Chưa có phiên hội thoại nào đang diễn ra để gửi phản hồi.</p>
              <button
                onClick={onClose}
                className="text-xs font-semibold px-4 py-2 bg-zinc-900 text-white rounded-xl shadow-xs cursor-pointer"
              >
                Đóng
              </button>
            </div>
          ) : (
            <form onSubmit={handleSubmit} className="space-y-4">
              {/* Tags Section */}
              <div>
                <label className="block text-xs font-bold text-zinc-700 uppercase tracking-wider mb-2.5">
                  1. Tiêu chí đánh giá chất lượng Routing:
                </label>
                <div className="flex flex-wrap gap-2">
                  {SESSION_FEEDBACK_TAGS.map(t => {
                    const selected = selectedTags.includes(t.label)
                    return (
                      <button
                        key={t.id}
                        type="button"
                        onClick={() => toggleTag(t.label)}
                        className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium border transition-all cursor-pointer ${
                          selected
                            ? 'bg-zinc-900 text-white border-zinc-900 shadow-2xs scale-[1.02]'
                            : 'bg-zinc-50 hover:bg-zinc-100/80 text-zinc-700 border-zinc-200/80'
                        }`}
                      >
                        <span>{t.icon}</span>
                        <span>{t.label}</span>
                      </button>
                    )
                  })}
                </div>
              </div>

              {/* Note Textarea */}
              <div>
                <div className="flex items-center justify-between mb-1.5">
                  <label className="text-xs font-bold text-zinc-700 uppercase tracking-wider">
                    2. Ghi chú thêm (tùy chọn):
                  </label>
                  <span className="text-[10px] font-mono text-zinc-400">{note.length}/500</span>
                </div>
                <textarea
                  value={note}
                  onChange={e => setNote(e.target.value.slice(0, 500))}
                  placeholder="Góp ý chi tiết về độ chính xác, tốc độ hoặc model..."
                  rows={3}
                  className="w-full text-xs border border-zinc-200 rounded-2xl p-3 focus:outline-none focus:ring-2 focus:ring-zinc-900/10 focus:border-zinc-900 text-zinc-800 resize-none transition-all placeholder:text-zinc-400"
                />
              </div>

              {/* Error Message */}
              {error && (
                <div className="p-3 rounded-xl bg-rose-50 border border-rose-200 text-rose-700 text-xs font-medium flex items-center gap-2">
                  <span>⚠️</span>
                  <span>{error}</span>
                </div>
              )}

              {/* Actions Footer */}
              <div className="flex items-center justify-end gap-2.5 pt-2 border-t border-zinc-100">
                <button
                  type="button"
                  onClick={onClose}
                  disabled={submitting}
                  className="px-4 py-2 rounded-xl text-xs font-semibold text-zinc-600 hover:text-zinc-950 hover:bg-zinc-100 transition-colors cursor-pointer"
                >
                  Hủy
                </button>
                <button
                  type="submit"
                  disabled={submitting}
                  className="inline-flex items-center gap-2 px-5 py-2 rounded-xl text-xs font-semibold text-white bg-zinc-900 hover:bg-zinc-800 active:scale-[0.99] transition-all shadow-xs cursor-pointer disabled:opacity-50"
                >
                  {submitting ? (
                    <>
                      <span className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                      <span>Đang gửi...</span>
                    </>
                  ) : (
                    <span>Gửi phản hồi</span>
                  )}
                </button>
              </div>
            </form>
          )}
        </div>
      </div>
    </div>
  )
}

// ─── Markdown & Code Rendering ──────────────────────────────────────────────

function CodeBlock({ lang, value }) {
  const [copied, setCopied] = useState(false)
  const copy = () => {
    navigator.clipboard.writeText(value)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }
  return (
    <div className="my-3 rounded-2xl border border-zinc-200 overflow-hidden text-sm shadow-xs">
      <div className="flex items-center justify-between px-4 py-2 bg-zinc-50 border-b border-zinc-200/80">
        <span className="text-[11px] font-mono font-medium text-zinc-500">{lang || 'code'}</span>
        <button onClick={copy} className="flex items-center gap-1.5 text-xs text-zinc-500 hover:text-zinc-900 transition-colors">
          <CopyIcon />
          <span>{copied ? 'Copied!' : 'Copy'}</span>
        </button>
      </div>
      <pre className="p-4 bg-white overflow-x-auto text-zinc-900 leading-relaxed font-mono text-xs whitespace-pre-wrap break-words">{value}</pre>
    </div>
  )
}

function normalizeMath(str) {
  return str
    .replace(/\\\[/g, '$$').replace(/\\\]/g, '$$')
    .replace(/\\\(/g, '$').replace(/\\\)/g, '$')
}

function Markdown({ children }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm, remarkMath]}
      rehypePlugins={[rehypeKatex]}
      components={{
        p:      ({ children }) => <p className="text-sm text-zinc-900 mb-3 last:mb-0 leading-relaxed break-words">{children}</p>,
        strong: ({ children }) => <strong className="font-semibold text-zinc-950">{children}</strong>,
        em:     ({ children }) => <em className="italic text-zinc-800">{children}</em>,
        h1:     ({ children }) => <h1 className="text-base font-bold text-zinc-950 mt-4 mb-2">{children}</h1>,
        h2:     ({ children }) => <h2 className="text-sm font-bold text-zinc-950 mt-3 mb-1.5">{children}</h2>,
        h3:     ({ children }) => <h3 className="text-sm font-semibold text-zinc-900 mt-3 mb-1">{children}</h3>,
        ul:     ({ children }) => <ul className="list-disc list-inside space-y-1 my-2 text-sm text-zinc-900">{children}</ul>,
        ol:     ({ children }) => <ol className="list-decimal list-outside ml-4 space-y-2.5 my-3 text-sm text-zinc-900">{children}</ol>,
        li:     ({ children }) => <li className="text-sm text-zinc-900 leading-relaxed pl-1">{children}</li>,
        hr:     ()             => <hr className="border-zinc-200 my-4" />,
        table:  ({ children }) => <div className="overflow-x-auto my-3"><table className="text-xs border-collapse w-full">{children}</table></div>,
        thead:  ({ children }) => <thead className="bg-zinc-100 border-b border-zinc-200">{children}</thead>,
        th:     ({ children }) => <th className="border border-zinc-200 px-3 py-2 text-left font-semibold text-zinc-900">{children}</th>,
        td:     ({ children }) => <td className="border border-zinc-200 px-3 py-2 text-zinc-800">{children}</td>,
        tr:     ({ children }) => <tr className="even:bg-zinc-50">{children}</tr>,
        pre:    ({ children }) => <>{children}</>,
        code({ className, children }) {
          const lang = /language-(\w+)/.exec(className || '')?.[1]
          const text = String(children).replace(/\n$/, '')
          if (lang !== undefined || text.includes('\n')) {
            return <CodeBlock lang={lang || 'text'} value={text} />
          }
          return <code className="text-xs font-mono bg-zinc-100 text-zinc-900 px-1.5 py-0.5 rounded-md font-medium">{children}</code>
        },
      }}
    >
      {typeof children === 'string' ? normalizeMath(children) : children}
    </ReactMarkdown>
  )
}

function TypingDots() {
  return (
    <div className="flex items-center gap-2 py-1">
      <div className="flex items-center gap-1">
        {[0, 1, 2].map(i => (
          <span key={i} className="w-1.5 h-1.5 bg-zinc-400 rounded-full animate-bounce"
            style={{ animationDelay: `${i * 0.15}s` }} />
        ))}
      </div>
      <span className="text-xs text-zinc-400 italic">Sidekick is thinking...</span>
    </div>
  )
}

// ─── Policy / Override Config ───────────────────────────────────────────────

const POLICIES = [
  { label: 'Balanced',   value: 'balanced' },
  { label: 'Quality',    value: 'quality_first' },
  { label: 'Cost First', value: 'cost_first' },
]

const OVERRIDES = [
  { label: 'Auto',          value: null },
  { label: 'Low-cost',      value: 'T1' },
  { label: 'Balanced',      value: 'T2' },
  { label: 'High-quality',  value: 'T3' },
]

const CLASSIFIER_VERSIONS = [
  { label: 'LLM',       value: 'v2' },
  { label: 'Heuristic', value: 'v1.5' },
]

function PillDropdown({ prefix, value, options, onChange, disabled, title, dataTour }) {
  const [isOpen, setIsOpen] = useState(false)
  const [pos, setPos] = useState({ top: 0, right: 0 })
  const ref = useRef(null)
  const menuRef = useRef(null)

  useEffect(() => {
    if (!isOpen) return
    function handleClickOutside(e) {
      if (!ref.current?.contains(e.target) && !menuRef.current?.contains(e.target)) {
        setIsOpen(false)
      }
    }
    // Menu is portaled with position:fixed — close on page scroll/resize to avoid stale placement.
    // KHÔNG dùng capture: capture bắt cả scroll ngang của toolbar (overflow-x-auto) khi bấm pill
    // ngoài cùng phải → menu tự đóng ngay. Không capture thì chỉ scroll cửa sổ thật mới đóng.
    const close = () => setIsOpen(false)
    document.addEventListener('mousedown', handleClickOutside)
    window.addEventListener('scroll', close)
    window.addEventListener('resize', close)
    return () => {
      document.removeEventListener('mousedown', handleClickOutside)
      window.removeEventListener('scroll', close)
      window.removeEventListener('resize', close)
    }
  }, [isOpen])

  // Đo vị trí nút để đặt menu (portal) — vì toolbar có overflow-x-auto sẽ clip menu absolute.
  const toggleOpen = () => {
    if (!isOpen && ref.current) {
      const r = ref.current.getBoundingClientRect()
      setPos({ top: r.bottom + 6, right: window.innerWidth - r.right })
    }
    setIsOpen(prev => !prev)
  }

  const selectedOption = options.find(o => o.value === value) || options[0]
  const buttonLabel = prefix ? `${prefix}: ${selectedOption?.label}` : selectedOption?.label

  return (
    <div ref={ref} className="relative inline-block text-left">
      <button
        type="button"
        data-tour={dataTour}
        disabled={disabled}
        onClick={toggleOpen}
        title={title}
        className={`text-[11px] font-medium rounded-full px-2.5 py-1 border transition-all inline-flex items-center gap-1.5 cursor-pointer shadow-2xs select-none disabled:opacity-50 ${
          isOpen
            ? 'bg-zinc-200/90 text-zinc-950 border-zinc-300 shadow-xs'
            : 'bg-zinc-100/90 hover:bg-zinc-200/70 text-zinc-700 hover:text-zinc-950 border-zinc-200/80'
        }`}
      >
        <span>{buttonLabel}</span>
        <svg
          className={`w-3 h-3 text-zinc-400 transition-transform duration-150 ${isOpen ? 'rotate-180 text-zinc-700' : ''}`}
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {isOpen && createPortal(
        <div
          ref={menuRef}
          style={{ position: 'fixed', top: pos.top, right: pos.right }}
          className="min-w-[130px] bg-white rounded-xl border border-zinc-200 shadow-xl p-1 z-[100] animate-in select-none"
          onClick={e => e.stopPropagation()}
        >
          {options.map(option => {
            const isSelected = option.value === value
            return (
              <button
                key={String(option.value)}
                type="button"
                onClick={() => {
                  onChange(option.value)
                  setIsOpen(false)
                }}
                className={`w-full text-left px-2.5 py-1.5 text-xs rounded-lg transition-colors flex items-center justify-between cursor-pointer ${
                  isSelected
                    ? 'bg-zinc-100 font-semibold text-zinc-900'
                    : 'text-zinc-700 hover:bg-zinc-50 hover:text-zinc-900'
                }`}
              >
                <span>{option.label}</span>
                {isSelected && (
                  <svg className="w-3.5 h-3.5 text-zinc-900 shrink-0 ml-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7" />
                  </svg>
                )}
              </button>
            )
          })}
        </div>,
        document.body
      )}
    </div>
  )
}


// ─── Memoized Message Item ──────────────────────────────────────────────────

const MessageItem = memo(function MessageItem({ msg, feedback, copied, routingExpanded, showRoutingDetails, onFeedback, onCopy, onToggleRouting }) {
  if (msg.role === 'user') {
    return (
      <div className="flex justify-end pt-8 pb-3 first:pt-0">
        <div className="bg-zinc-100 text-zinc-900 rounded-2xl px-5 py-2.5 text-sm max-w-xl shadow-2xs font-normal whitespace-pre-wrap break-words leading-relaxed">
          {msg.content}
        </div>
      </div>
    )
  }

  return (
    <div className="flex items-start gap-3 my-3 max-w-[93%] pr-1 sm:pr-2">
      <OriginAiAvatar />
      <div className="flex-1 min-w-0">
        {msg.loading ? (
          <TypingDots />
        ) : msg.error ? (
          <p className="text-sm text-rose-600 font-medium">{msg.content}</p>
        ) : (
          <div className="text-sm text-zinc-900 leading-relaxed font-sans">
            <Markdown>{msg.content}</Markdown>
          </div>
        )}

        {!msg.loading && !msg.error && (
          <div className="flex items-center gap-3 mt-3 pt-1 text-zinc-400">
            <button
              onClick={() => onFeedback(msg.id, 'up')}
              className={`hover:text-zinc-800 transition-colors ${feedback === 'up' ? 'text-zinc-900 font-bold' : ''}`}
              title="Hữu ích"
            >
              <ThumbsUpIcon />
            </button>
            <button
              onClick={() => onFeedback(msg.id, 'down')}
              className={`hover:text-zinc-800 transition-colors ${feedback === 'down' ? 'text-zinc-900 font-bold' : ''}`}
              title="Chưa hài lòng"
            >
              <ThumbsDownIcon />
            </button>
            <button
              onClick={() => onCopy(msg.id, msg.content)}
              className="hover:text-zinc-800 transition-colors relative group"
              title="Sao chép câu trả lời"
            >
              <CopyIcon />
              {copied && (
                <span className="absolute left-full ml-1 text-[10px] text-zinc-600 bg-white px-1.5 py-0.5 rounded border border-zinc-200 shadow-xs whitespace-nowrap">
                  Copied!
                </span>
              )}
            </button>

            {msg.routing && (
              <button
                type="button"
                onClick={() => onToggleRouting(msg.id)}
                className={`ml-auto inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs transition-all cursor-pointer border ${
                  routingExpanded || showRoutingDetails
                    ? 'bg-zinc-900 text-white border-zinc-900 shadow-xs'
                    : 'bg-white hover:bg-zinc-100/80 text-zinc-700 border-zinc-200/90 shadow-2xs'
                }`}
                title="Bấm để xem chi tiết cách tính điểm độ khó và các tín hiệu routing"
              >
                <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold border ${
                  routingExpanded || showRoutingDetails
                    ? 'bg-white/20 text-white border-white/30'
                    : TIER_COLOR[msg.routing.tierCode] || 'bg-zinc-100 text-zinc-700'
                }`}>
                  {msg.routing.tierCode} · {msg.routing.difficulty}
                </span>
                <span className={`font-mono text-[11px] ${
                  routingExpanded || showRoutingDetails ? 'text-zinc-300' : 'text-zinc-500'
                }`}>
                  {msg.routing.modelName} · {msg.routing.latencyLabel}
                </span>
                <svg
                  className={`w-3 h-3 transition-transform duration-200 ${
                    routingExpanded || showRoutingDetails ? 'rotate-180 text-white' : 'text-zinc-400'
                  }`}
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                </svg>
              </button>
            )}
          </div>
        )}

        {(routingExpanded || showRoutingDetails) && msg.routing && (
          <ScoreBreakdownCard routing={msg.routing} />
        )}
      </div>
    </div>
  )
})

// ─── Recent Chats List (Lazy-loaded / Infinite Scroll) ──────────────────────

const RecentChatsList = memo(function RecentChatsList({
  sessionsList,
  totalSessions,
  sessionId,
  messages,
  discussionTitle,
  selectSession,
  loadingMore,
  hasMore,
  onLoadMore,
}) {
  const sentinelRef = useRef(null)

  useEffect(() => {
    const el = sentinelRef.current
    if (!el || !hasMore || loadingMore) return

    const observer = new IntersectionObserver(
      entries => {
        if (entries[0]?.isIntersecting) {
          onLoadMore()
        }
      },
      { rootMargin: '80px' }
    )

    observer.observe(el)
    return () => observer.disconnect()
  }, [hasMore, loadingMore, onLoadMore])

  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-xs font-bold text-zinc-900 uppercase tracking-wider">Recent chats</h3>
        {totalSessions > 0 && (
          <span className="text-[10px] text-zinc-400 font-mono font-medium">{totalSessions}</span>
        )}
      </div>

      {/* In-progress new conversation not yet synced in sessionsList */}
      {messages.length > 0 && !sessionsList.some(s => s.session_id === sessionId) && (
        <div className="mb-2">
          <div className="text-[10px] font-bold text-zinc-400 uppercase tracking-wider mb-1 px-1">Today</div>
          <div
            className="p-2 px-3 rounded-xl bg-zinc-200/75 text-xs font-semibold text-zinc-900 truncate shadow-2xs cursor-default"
            title={discussionTitle}
          >
            {discussionTitle}
          </div>
        </div>
      )}

      {/* Sessions History List */}
      {sessionsList.length > 0 ? (
        <div className="space-y-1">
          {sessionsList.map(s => {
            const isCurrent = s.session_id === sessionId && messages.length > 0
            const displayName = s.title || `Chat ${s.session_id.slice(0, 8)}`
            return (
              <div
                key={s.session_id}
                onClick={() => selectSession(s.session_id)}
                className={`p-2 px-3 rounded-xl text-xs truncate cursor-pointer transition-all ${
                  isCurrent
                    ? 'bg-zinc-200/80 text-zinc-900 font-semibold shadow-2xs'
                    : 'text-zinc-700 hover:text-zinc-950 hover:bg-zinc-100/80 font-medium'
                }`}
                title={displayName}
              >
                {displayName}
              </div>
            )
          })}

          {/* Sentinel trigger for infinite scroll */}
          {hasMore && (
            <div ref={sentinelRef} className="py-2.5 flex items-center justify-center text-zinc-400">
              {loadingMore ? (
                <div className="flex items-center gap-1.5 text-[11px] text-zinc-500 font-medium">
                  <span className="w-3.5 h-3.5 border-2 border-zinc-300 border-t-zinc-700 rounded-full animate-spin" />
                  <span>Đang tải thêm...</span>
                </div>
              ) : (
                <div className="h-2" />
              )}
            </div>
          )}
        </div>
      ) : messages.length === 0 ? (
        <div className="text-xs text-zinc-400 py-1.5 px-1 italic">Chưa có hội thoại nào</div>
      ) : null}
    </div>
  )
})

// ─── Main Component ─────────────────────────────────────────────────────────

export default function Playground({ sessionFeedbackOpen, onSessionFeedbackClose, onSessionStart }) {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [policy, setPolicy] = useState('balanced')
  const [override, setOverride] = useState(null)
  const [classifierVersion, setClassifierVersion] = useState('v2')
  const [loading, setLoading] = useState(false)
  const [connected, setConnected] = useState(null)
  const [showRoutingDetails, setShowRoutingDetails] = useState(false)
  const [expandedRoutingIds, setExpandedRoutingIds] = useState({})
  const [internalFeedbackOpen, setInternalFeedbackOpen] = useState(false)
  const [sessionId, setSessionId] = useState(null)
  const PAGE_SIZE = 15
  const [sessionsList, setSessionsList] = useState([])
  const [totalSessions, setTotalSessions] = useState(0)
  const [sessionsLoading, setSessionsLoading] = useState(false)
  const [sessionsLoadingMore, setSessionsLoadingMore] = useState(false)
  const hasMoreSessions = sessionsList.length < totalSessions
  const [feedbackState, setFeedbackState] = useState({}) // msgId -> 'up' | 'down'
  const [copiedId, setCopiedId] = useState(null)
  const [mobileHistoryOpen, setMobileHistoryOpen] = useState(false)

  const bottomRef = useRef(null)
  const textareaRef = useRef(null)
  const apiHistory = useRef([])

  const refreshSessions = useCallback(async () => {
    setSessionsLoading(true)
    try {
      const data = await fetchSessions(PAGE_SIZE, 0)
      if (data?.items) {
        setSessionsList(data.items)
        setTotalSessions(data.total ?? data.items.length)
      }
    } catch {
      // ignore
    } finally {
      setSessionsLoading(false)
    }
  }, [])

  const loadMoreSessions = useCallback(async () => {
    if (sessionsLoading || sessionsLoadingMore || !hasMoreSessions) return
    setSessionsLoadingMore(true)
    try {
      const data = await fetchSessions(PAGE_SIZE, sessionsList.length)
      if (data?.items && data.items.length > 0) {
        setSessionsList(prev => {
          const existingIds = new Set(prev.map(s => s.session_id))
          const newItems = data.items.filter(s => !existingIds.has(s.session_id))
          return [...prev, ...newItems]
        })
        if (typeof data.total === 'number') {
          setTotalSessions(data.total)
        }
      } else {
        setTotalSessions(sessionsList.length)
      }
    } catch {
      // ignore
    } finally {
      setSessionsLoadingMore(false)
    }
  }, [sessionsLoading, sessionsLoadingMore, hasMoreSessions, sessionsList.length])

  useEffect(() => {
    refreshSessions()
    checkHealth()
      .then(data => setConnected(data?.status === 'ok' || data?.status === 'degraded'))
      .catch(() => setConnected(false))
  }, [refreshSessions])

  // ponytail: scroll only when new messages are added (length changes),
  // not during streaming content updates — user controls their own scroll.
  const msgCount = messages.length
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [msgCount])

  useEffect(() => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    const maxH = 120
    el.style.height = Math.min(el.scrollHeight, maxH) + 'px'
    el.style.overflowY = el.scrollHeight > maxH ? 'auto' : 'hidden'
  }, [input])

  const startNewChat = useCallback(() => {
    setMessages([])
    apiHistory.current = []
    setSessionId(null)
    setMobileHistoryOpen(false)
  }, [])

  const selectSession = useCallback(async (sid) => {
    if (sid === sessionId && messages.length > 0) {
      setMobileHistoryOpen(false)
      return
    }
    try {
      const detail = await fetchSessionHistory(sid)
      if (detail) {
        setSessionId(sid)
        onSessionStart?.()

        const reconstructed = []
        const hist = []

        for (const turn of detail.turns || []) {
          const userMsgs = (turn.messages || []).filter(m => m.role === 'user')
          const userText = userMsgs[userMsgs.length - 1]?.content || ''
          if (userText) {
            reconstructed.push({ id: `${turn.request_id}-user`, role: 'user', content: userText })
            hist.push({ role: 'user', content: userText })
          }
          const assistantText = turn.response_content || ''
          reconstructed.push({
            id: `${turn.request_id}-assistant`,
            role: 'assistant',
            content: assistantText,
            routing: turn.tier ? mapRouting({
              request_id: turn.request_id,
              tier: turn.tier,
              difficulty_score: turn.difficulty_score,
              model_used: turn.model,
              provider: turn.provider,
              cost_usd: turn.cost_usd,
              latency_total_ms: turn.latency_total_ms,
              latency_router_ms: turn.latency_router_ms,
              signals: turn.signals || [],
            }) : null,
          })
          if (assistantText) hist.push({ role: 'assistant', content: assistantText })
        }

        setMessages(reconstructed)
        apiHistory.current = hist
      }
    } catch (e) {
      console.error('Failed to load session history:', e)
    }
  }, [sessionId, messages.length, onSessionStart])

  const handleSendPrompt = useCallback(async (customText) => {
    const text = (typeof customText === 'string' ? customText : input).trim()
    if (!text || loading) return

    const userMsg = { id: Date.now(), role: 'user', content: text }
    const loadingMsg = { id: Date.now() + 1, role: 'assistant', loading: true }

    apiHistory.current.push({ role: 'user', content: text })
    setMessages(prev => [...prev, userMsg, loadingMsg])
    setInput('')
    setLoading(true)

    let sid = sessionId
    if (!sid) {
      sid = (typeof crypto !== 'undefined' && crypto.randomUUID) ? crypto.randomUUID() : (await createSession().catch(() => null))?.session_id
      if (sid) { setSessionId(sid); onSessionStart?.() }
    }

    const t0 = Date.now()
    try {
      const res = await sendChatStream(apiHistory.current, policy, override, sid, classifierVersion)
      let requestId = res.headers.get('X-SR-Request-Id')
      const modelUsed = res.headers.get('X-SR-Model')
      const tierHeader = res.headers.get('X-SR-Tier')
      const scoreHeader = res.headers.get('X-SR-Score')
      const costHeader = res.headers.get('X-SR-Cost-USD')
      const providerHeader = res.headers.get('X-SR-Provider')

      const initialRouting = tierHeader ? mapRouting({
        request_id: requestId,
        tier: tierHeader,
        difficulty_score: scoreHeader ? parseInt(scoreHeader, 10) : 0,
        model_used: modelUsed,
        provider: providerHeader,
        cost_usd: costHeader ? parseFloat(costHeader) : null,
        signals: [],
      }) : null

      const msgId = Date.now() + 2
      setMessages(prev => [...prev.slice(0, -1), { id: msgId, role: 'assistant', content: '', streaming: true, modelUsed, routing: initialRouting }])

      let totalContent = ''
      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buf = ''
      let rafPending = false

      const flushContent = () => {
        const snapshot = totalContent
        setMessages(prev => prev.map(m => m.id === msgId ? { ...m, content: snapshot } : m))
        rafPending = false
      }

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buf += decoder.decode(value, { stream: true })
        const lines = buf.split('\n')
        buf = lines.pop()
        let dirty = false
        for (const line of lines) {
          if (!line.startsWith('data:')) continue
          const payload = line.slice(5).trim()
          if (!payload || payload === '[DONE]') continue
          const chunk = JSON.parse(payload)
          if (chunk.error) throw new Error(chunk.error.message || 'Provider error')
          if (chunk.smartroute_fallback) {
            const fb = chunk.smartroute_fallback
            setMessages(prev => prev.map(m => m.id === msgId ? { ...m, modelUsed: fb.to, fallbackFrom: fb.from } : m))
            continue
          }
          if (!requestId && chunk.id?.startsWith('chatcmpl-')) {
            const hex = chunk.id.slice(9)
            requestId = `${hex.slice(0,8)}-${hex.slice(8,12)}-${hex.slice(12,16)}-${hex.slice(16,20)}-${hex.slice(20)}`
          }
          const delta = chunk.choices?.[0]?.delta?.content ?? ''
          if (delta) {
            totalContent += delta
            dirty = true
          }
        }
        if (dirty && !rafPending) {
          rafPending = true
          requestAnimationFrame(flushContent)
        }
      }
      // flush any remaining content after stream ends
      if (rafPending) { cancelAnimationFrame(0); flushContent() }
      else if (totalContent) { flushContent() }

      if (!totalContent) throw new Error('Không nhận được phản hồi từ provider.')

      const elapsed = ((Date.now() - t0) / 1000).toFixed(1) + 's'
      apiHistory.current.push({ role: 'assistant', content: totalContent })
      setMessages(prev => prev.map(m => m.id === msgId ? { ...m, streaming: false, latency: elapsed } : m))
      refreshSessions()

      if (requestId) {
        const mid = msgId
        ;(async () => {
          for (let i = 0; i < 6; i++) {
            await new Promise(r => setTimeout(r, 600))
            const usage = await fetchUsage(requestId).catch(() => null)
            if (usage?.smartroute) {
              setMessages(prev => prev.map(m =>
                m.id === mid ? { ...m, routing: mapRouting(usage.smartroute) } : m
              ))
              if (usage.status === 'complete') return
            }
          }
        })()
      }
    } catch (err) {
      setMessages(prev => [
        ...prev.slice(0, -1),
        { id: Date.now() + 2, role: 'assistant', content: formatPlaygroundError(err), error: true },
      ])
      apiHistory.current.pop()
    } finally {
      setLoading(false)
    }
  }, [input, loading, policy, override, classifierVersion, sessionId, onSessionStart, refreshSessions])

  const onKey = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSendPrompt()
    }
  }

  const handleCopy = useCallback((id, text) => {
    navigator.clipboard.writeText(text)
    setCopiedId(id)
    setTimeout(() => setCopiedId(null), 1500)
  }, [])

  const toggleFeedback = useCallback((msgId, type) => {
    setFeedbackState(prev => ({
      ...prev,
      [msgId]: prev[msgId] === type ? null : type,
    }))
  }, [])

  const toggleRouting = useCallback((msgId) => {
    setExpandedRoutingIds(prev => ({ ...prev, [msgId]: !prev[msgId] }))
  }, [])

  // Determine current active discussion title
  const firstUserMsg = messages.find(m => m.role === 'user')
  const discussionTitle = firstUserMsg ? firstUserMsg.content : 'New Conversation'

  return (
    <div className="flex h-full w-full overflow-hidden font-sans select-none relative">
      {/* ─── Mobile Slide-over Chat History Drawer ─────────────────────── */}
      {mobileHistoryOpen && (
        <div className="fixed inset-0 z-40 md:hidden flex">
          <div
            className="fixed inset-0 bg-black/40 backdrop-blur-xs animate-fadeIn"
            onClick={() => setMobileHistoryOpen(false)}
          />
          <aside className="relative w-80 max-w-[85vw] bg-white z-50 shadow-2xl flex flex-col justify-between p-5 select-none h-full border-r border-zinc-200 animate-slide-in-left overflow-hidden">
            <div className="flex items-center justify-between pb-3 mb-2 border-b border-zinc-100 flex-none">
              <span className="text-xs font-bold text-zinc-900 uppercase tracking-wider">Lịch sử hội thoại</span>
              <button
                onClick={() => setMobileHistoryOpen(false)}
                className="w-7 h-7 rounded-full flex items-center justify-center text-zinc-400 hover:text-zinc-900 hover:bg-zinc-100 text-sm font-bold"
              >
                ✕
              </button>
            </div>

            <div className="flex-1 min-h-0 flex flex-col space-y-4 overflow-hidden">
              {/* Header: AI ROUTER + NEW CHAT */}
              <div className="flex items-center justify-between flex-none">
                <span className="text-[11px] font-bold tracking-widest text-zinc-400 uppercase">
                  AI Router
                </span>
                <button
                  onClick={startNewChat}
                  className="text-[10px] font-bold tracking-wider uppercase px-3 py-1 rounded-full border border-zinc-200 text-zinc-700 hover:text-zinc-950 hover:border-zinc-300 hover:bg-zinc-50 transition-all shadow-xs"
                >
                  New Chat
                </button>
              </div>

              {/* Action Card: Test Smart Routing */}
              <div
                onClick={() => {
                  handleSendPrompt('Hãy phân tích và viết thuật toán tìm đường đi ngắn nhất Floyd-Warshall')
                  setMobileHistoryOpen(false)
                }}
                className="group flex items-center justify-between p-3.5 px-4 rounded-2xl border border-zinc-200 hover:border-zinc-300 hover:shadow-xs transition-all cursor-pointer bg-white flex-none"
              >
                <div className="flex items-center gap-3">
                  <PlanAiIcon />
                  <span className="text-sm font-semibold text-zinc-900">Test Smart Routing</span>
                </div>
                <ChevronRight />
              </div>

              {/* Recent chats */}
              <div className="flex-1 min-h-0 overflow-y-auto pr-1">
                <RecentChatsList
                  sessionsList={sessionsList}
                  totalSessions={totalSessions}
                  sessionId={sessionId}
                  messages={messages}
                  discussionTitle={discussionTitle}
                  selectSession={selectSession}
                  loadingMore={sessionsLoadingMore}
                  hasMore={hasMoreSessions}
                  onLoadMore={loadMoreSessions}
                />
              </div>
            </div>

            {/* Bottom Gateway Status in Drawer (Fixed at bottom) */}
            <div className="pt-3 mt-3 border-t border-zinc-100 flex items-center justify-between text-[11px] text-zinc-400 flex-none shrink-0 bg-white">
              <span className="flex items-center gap-1.5">
                <span className={`w-2 h-2 rounded-full ${connected ? 'bg-emerald-500' : 'bg-zinc-300'}`} />
                {connected ? 'Gateway Connected' : 'Connecting...'}
              </span>
              <button
                onClick={() => setShowRoutingDetails(prev => !prev)}
                className="hover:text-zinc-800 underline transition-colors cursor-pointer"
              >
                {showRoutingDetails ? 'Ẩn Routing' : 'Chi tiết Routing'}
              </button>
            </div>
          </aside>
        </div>
      )}

      {/* ═══════════════════════════════════════════════════════════════════════
          DESKTOP LEFT COLUMN: SUB-SIDEBAR / PROMPT HUB (~320px inside card)
      ═══════════════════════════════════════════════════════════════════════ */}
      <aside data-tour="sidebar" className="hidden md:flex w-72 lg:w-80 flex-none border-r border-zinc-100 flex-col justify-between p-5 lg:p-6 h-full min-h-0 overflow-hidden">
        <div className="flex-1 min-h-0 flex flex-col space-y-4 overflow-hidden">
          {/* Header: AI ROUTER + NEW CHAT */}
          <div className="flex items-center justify-between flex-none">
            <span className="text-[11px] font-bold tracking-widest text-zinc-400 uppercase">
              AI Router
            </span>
            <button
              onClick={startNewChat}
              className="text-[10px] font-bold tracking-wider uppercase px-3 py-1 rounded-full border border-zinc-200 text-zinc-700 hover:text-zinc-950 hover:border-zinc-300 hover:bg-zinc-50 transition-all shadow-xs"
            >
              New Chat
            </button>
          </div>

          {/* Action Card: Test Smart Routing */}
          <div
            onClick={() => handleSendPrompt('Hãy phân tích và viết thuật toán tìm đường đi ngắn nhất Floyd-Warshall')}
            className="group flex items-center justify-between p-3.5 px-4 rounded-2xl border border-zinc-200 hover:border-zinc-300 hover:shadow-xs transition-all cursor-pointer bg-white flex-none"
          >
            <div className="flex items-center gap-3">
              <PlanAiIcon />
              <span className="text-sm font-semibold text-zinc-900">Test Smart Routing</span>
            </div>
            <ChevronRight />
          </div>

          {/* Recent chats (Scrollable area) */}
          <div className="flex-1 min-h-0 overflow-y-auto pr-1">
            <RecentChatsList
              sessionsList={sessionsList}
              totalSessions={totalSessions}
              sessionId={sessionId}
              messages={messages}
              discussionTitle={discussionTitle}
              selectSession={selectSession}
              loadingMore={sessionsLoadingMore}
              hasMore={hasMoreSessions}
              onLoadMore={loadMoreSessions}
            />
          </div>
        </div>

        {/* Bottom Gateway Status (Fixed firmly at bottom) */}
        <div className="pt-3 mt-3 border-t border-zinc-100 flex items-center justify-between text-[11px] text-zinc-400 flex-none shrink-0 bg-white">
          <span className="flex items-center gap-1.5">
            <span className={`w-2 h-2 rounded-full ${connected ? 'bg-emerald-500' : 'bg-zinc-300'}`} />
            {connected ? 'Gateway Connected' : 'Connecting...'}
          </span>
          <button
            onClick={() => setShowRoutingDetails(prev => !prev)}
            className="hover:text-zinc-800 underline transition-colors cursor-pointer"
          >
            {showRoutingDetails ? 'Ẩn Routing' : 'Chi tiết Routing'}
          </button>
        </div>
      </aside>

      {/* ═══════════════════════════════════════════════════════════════════════
          RIGHT COLUMN: CONVERSATION CANVAS & INPUT
      ═══════════════════════════════════════════════════════════════════════ */}
      <section className="flex-1 flex flex-col min-w-0 h-full p-3 sm:p-5 md:p-6 pt-3 sm:pt-4 relative">
        {/* Top Header inside Canvas */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between pb-2.5 sm:pb-3.5 mb-1.5 sm:mb-2 flex-none border-b border-zinc-100/80 gap-2">
          <div className="flex items-center justify-between sm:justify-start gap-2 min-w-0">
            {/* Mobile History Drawer Button */}
            <button
              type="button"
              onClick={() => setMobileHistoryOpen(true)}
              className="md:hidden flex items-center gap-1.5 px-2.5 py-1 rounded-full border border-zinc-200 bg-zinc-50 hover:bg-zinc-100 text-zinc-700 text-xs font-semibold shadow-2xs shrink-0"
              title="Xem lịch sử trò chuyện"
            >
              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              <span>Lịch sử</span>
            </button>

            <span className="text-[11px] font-bold tracking-widest text-zinc-500 uppercase truncate max-w-[150px] sm:max-w-xs md:max-w-md">
              {discussionTitle}
            </span>
          </div>

          <div className="flex items-center gap-1.5 overflow-x-auto no-scrollbar py-0.5 justify-start sm:justify-end">
            {sessionId && messages.length > 0 && (
              <button
                type="button"
                onClick={() => setInternalFeedbackOpen(true)}
                className="inline-flex items-center gap-1.5 text-[11px] font-semibold text-zinc-800 bg-white hover:bg-zinc-100/90 border border-zinc-200/90 px-2.5 py-1 rounded-full transition-all shadow-2xs cursor-pointer shrink-0"
                title="Gửi phản hồi đánh giá toàn bộ phiên hội thoại này"
              >
                <span>✨ Phản hồi</span>
              </button>
            )}

            {/* Classifier Version Selector */}
            <PillDropdown
              prefix="Classifier"
              dataTour="classifier"
              value={classifierVersion}
              options={CLASSIFIER_VERSIONS}
              onChange={setClassifierVersion}
              disabled={loading}
              title="Chọn phiên bản Classifier"
            />

            {/* Policy Selector */}
            <PillDropdown
              prefix="Policy"
              dataTour="policy"
              value={policy}
              options={POLICIES}
              onChange={setPolicy}
              disabled={loading}
              title="Chọn chính sách định tuyến"
            />

            {/* Tier Override Selector */}
            <PillDropdown
              prefix="Tier"
              value={override}
              options={OVERRIDES}
              onChange={setOverride}
              disabled={loading}
              title="Ghi đè Tier (Manual Override)"
            />

            <button
              onClick={startNewChat}
              className="p-1 hover:bg-zinc-100 rounded-full transition-colors cursor-pointer shrink-0"
              title="Tạo đoạn chat mới"
            >
              <ThreeDotsIcon />
            </button>
          </div>
        </div>

        {/* Messages Stream Scroll Area / New Chat Empty State */}
        {messages.length === 0 ? (
          <div className="flex-1 flex flex-col items-center justify-center text-center px-4 py-8 select-none">
            <div className="w-12 h-12 rounded-2xl border-2 border-zinc-900 flex items-center justify-center mb-4 shadow-2xs">
              <div className="w-3.5 h-3.5 bg-zinc-900 rounded-xs" />
            </div>
            <h2 className="text-lg sm:text-xl font-bold tracking-tight text-zinc-900 mb-1.5">
              What would you like to route today?
            </h2>
            <p className="text-xs text-zinc-400 max-w-md leading-relaxed">
              Nhập câu hỏi vào thanh bên dưới để bắt đầu kiểm tra phân loại độ khó (T1/T2/T3) và định tuyến tự động.
            </p>
          </div>
        ) : (
          <div className="flex-1 overflow-y-auto pr-1 sm:pr-2 space-y-4 sm:space-y-6 select-text touch-scroll">
            {messages.map((msg, idx) => (
              <MessageItem
                key={msg.id || idx}
                msg={msg}
                feedback={feedbackState[msg.id]}
                copied={copiedId === msg.id}
                routingExpanded={!!expandedRoutingIds[msg.id]}
                showRoutingDetails={showRoutingDetails}
                onFeedback={toggleFeedback}
                onCopy={handleCopy}
                onToggleRouting={toggleRouting}
              />
            ))}
            <div ref={bottomRef} />
          </div>
        )}

        {/* ═════════════════════════════════════════════════════════════════════
            DIVE DEEPER SUGGESTION PILLS (Aligned Right)
        ═════════════════════════════════════════════════════════════════════ */}


        {/* ═════════════════════════════════════════════════════════════════════
            FLOATING PILL INPUT BAR
        ═════════════════════════════════════════════════════════════════════ */}
        <div className="pt-2 flex-none">
          <div className="rounded-full border border-zinc-200 bg-white shadow-xs px-4 py-2 flex items-center gap-3 focus-within:border-zinc-300 focus-within:shadow-sm transition-all">
            {/* Sparkle Icon */}
            <div className="text-zinc-400 flex-shrink-0">
              <SparkleIcon className="w-4 h-4" />
            </div>

            {/* Input textarea */}
            <textarea
              data-tour="input"
              ref={textareaRef}
              rows={1}
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={onKey}
              disabled={loading}
              placeholder="Ask Sidekick"
              className="flex-1 resize-none bg-transparent text-sm text-zinc-900 placeholder-zinc-400 focus:outline-none disabled:opacity-50 font-sans"
            />


            {/* Send Button */}
            <button
              onClick={() => handleSendPrompt()}
              disabled={loading || !input.trim()}
              className="w-8 h-8 rounded-full bg-zinc-100 hover:bg-zinc-900 hover:text-white text-zinc-500 disabled:opacity-30 disabled:hover:bg-zinc-100 disabled:hover:text-zinc-500 flex items-center justify-center flex-shrink-0 transition-colors shadow-xs"
              title="Gửi câu hỏi"
            >
              <UpArrowIcon />
            </button>
          </div>

          {/* Footer Disclaimer */}
          <div className="text-center text-[11px] text-zinc-400 mt-2">
            Answers may contain inaccurate data. See{' '}
            <span className="underline hover:text-zinc-600 cursor-pointer">disclosures</span>
          </div>
        </div>
      </section>

      {/* Session Feedback Modal */}
      <SessionFeedbackModal
        isOpen={sessionFeedbackOpen || internalFeedbackOpen}
        onClose={() => {
          setInternalFeedbackOpen(false)
          onSessionFeedbackClose?.()
        }}
        sessionId={sessionId}
      />
    </div>
  )
}
