import { useCallback, useEffect, useState } from 'react'
import { AdminAuthError, fetchAdminConfig, updateAdminConfig } from '../api'

const POLICY_META = {
  balanced: {
    label: 'balanced',
    tag: 'Chuẩn',
    desc: 'Giữ nguyên điểm phân loại, fallback ưu tiên chất lượng rồi mới xét giá. Phù hợp cho hầu hết mọi use-case.',
    orderBadge: { text: 'Chất lượng → Giá', icon: '⚖️', bg: 'bg-blue-50 text-blue-700 border-blue-200' },
  },
  cost_first: {
    label: 'cost_first',
    tag: 'Tiết kiệm',
    desc: 'Giảm điểm phân loại trước khi map tier (dễ lọt T1/T2 hơn), fallback xếp theo model rẻ nhất. Dùng khi muốn tối ưu chi phí.',
    orderBadge: { text: 'Rẻ nhất trước', icon: '💰', bg: 'bg-emerald-50 text-emerald-700 border-emerald-200' },
  },
  quality_first: {
    label: 'quality_first',
    tag: 'Chất lượng',
    desc: 'Tăng điểm phân loại trước khi map tier (dễ leo T2/T3 hơn), fallback xếp theo model tốt nhất. Dùng khi cần độ chính xác cao.',
    orderBadge: { text: 'Tốt nhất trước', icon: '🎯', bg: 'bg-purple-50 text-purple-700 border-purple-200' },
  },
}

const SYSTEM_DEFAULTS = {
  default_policy: 'balanced',
  policies: {
    balanced: { t1_max: 30, t2_max: 60, tier_shift: 0, order_by: 'quality_then_cost' },
    cost_first: { t1_max: 40, t2_max: 70, tier_shift: -10, order_by: 'cost_asc' },
    quality_first: { t1_max: 20, t2_max: 50, tier_shift: 10, order_by: 'quality_desc' },
  },
}

function Tooltip({ text, children }) {
  const [show, setShow] = useState(false)
  return (
    <span className="relative inline-flex items-center" onMouseEnter={() => setShow(true)} onMouseLeave={() => setShow(false)}>
      {children}
      {show && text && (
        <span className="absolute left-0 bottom-full mb-2 z-20 w-64 bg-stone-800 text-stone-100 text-xs rounded-lg px-3 py-2 shadow-xl leading-relaxed pointer-events-none">
          {text}
          <span className="absolute left-4 top-full -mt-1 border-4 border-transparent border-t-stone-800" />
        </span>
      )}
    </span>
  )
}

export default function ConfigPanel() {
  const [cfg, setCfg] = useState(null)
  const [draft, setDraft] = useState({ default_policy: 'balanced', policies: {} })
  const [msg, setMsg] = useState(null)
  const [saving, setSaving] = useState(false)
  const [loading, setLoading] = useState(true)
  const [authError, setAuthError] = useState(false)
  const [adminKeyInput, setAdminKeyInput] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setMsg(null)
    setAuthError(false)
    try {
      const data = await fetchAdminConfig()
      setCfg(data)
      const baseT1 = data.t1_max ?? 30
      const baseT2 = data.t2_max ?? 60
      const policiesDraft = {}

      Object.entries(data.policies || {}).forEach(([name, rule]) => {
        const shift = rule.tier_shift || 0
        policiesDraft[name] = {
          t1_max: Math.max(1, Math.min(99, baseT1 - shift)),
          t2_max: Math.max(2, Math.min(100, baseT2 - shift)),
          tier_shift: shift,
          order_by: rule.order_by,
        }
      })

      setDraft({
        default_policy: data.default_policy,
        policies: policiesDraft,
      })
    } catch (e) {
      if (e.name === 'AdminAuthError') {
        setAuthError(true)
        setCfg(null)  // clear protected state on 401/403 (#222)
      } else {
        setMsg({ ok: false, text: e.message })
      }
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  // Validation: Kiểm tra mọi policy đều thoả 0 < t1_max < t2_max <= 100
  const validationErrors = []
  if (draft.policies) {
    Object.entries(draft.policies).forEach(([name, p]) => {
      const t1 = Number(p.t1_max)
      const t2 = Number(p.t2_max)
      if (isNaN(t1) || isNaN(t2) || t1 <= 0 || t2 <= t1 || t2 > 100) {
        validationErrors.push(`${name}: Cần 0 < T1 (${t1}) < T2 (${t2}) ≤ 100`)
      }
    })
  }
  const isValid = validationErrors.length === 0

  // Kiểm tra có thay đổi so với server
  const hasChanges = Boolean(
    cfg &&
      (draft.default_policy !== cfg.default_policy ||
        Object.entries(draft.policies).some(([name, p]) => {
          const origRule = cfg.policies?.[name]
          if (!origRule) return true
          const origT1 = (cfg.t1_max ?? 30) - (origRule.tier_shift || 0)
          const origT2 = (cfg.t2_max ?? 60) - (origRule.tier_shift || 0)
          return Number(p.t1_max) !== origT1 || Number(p.t2_max) !== origT2
        }))
  )

  const handleReset = () => {
    if (!cfg) return
    const baseT1 = cfg.t1_max ?? 30
    const baseT2 = cfg.t2_max ?? 60
    const policiesDraft = {}
    Object.entries(cfg.policies || {}).forEach(([name, rule]) => {
      const shift = rule.tier_shift || 0
      policiesDraft[name] = {
        t1_max: Math.max(1, Math.min(99, baseT1 - shift)),
        t2_max: Math.max(2, Math.min(100, baseT2 - shift)),
        tier_shift: shift,
        order_by: rule.order_by,
      }
    })
    setDraft({
      default_policy: cfg.default_policy,
      policies: policiesDraft,
    })
    setMsg(null)
  }

  const handleRestoreDefaults = () => {
    setDraft(SYSTEM_DEFAULTS)
    setMsg({ ok: true, text: 'Đã nạp giá trị mặc định hệ thống. Bấm "Lưu thay đổi" để áp dụng.' })
  }

  const handleThresholdChange = (policyName, field, value) => {
    setDraft(d => ({
      ...d,
      policies: {
        ...d.policies,
        [policyName]: {
          ...d.policies[policyName],
          [field]: value,
        },
      },
    }))
  }

  const handleSave = async () => {
    if (!isValid) {
      setMsg({ ok: false, text: validationErrors[0] || 'Ngưỡng không hợp lệ.' })
      return
    }
    setSaving(true)
    setMsg(null)
    try {
      // Lấy ngưỡng chuẩn từ policy 'balanced' (hoặc policy đang chọn nếu không có balanced)
      const basePolicy = draft.policies['balanced'] || draft.policies[draft.default_policy]
      const baseT1 = Number(basePolicy?.t1_max ?? 30)
      const baseT2 = Number(basePolicy?.t2_max ?? 60)

      const policiesPatch = {}
      Object.entries(draft.policies).forEach(([name, p]) => {
        const t1 = Number(p.t1_max)
        // tier_shift = baseT1 - t1
        const shift = baseT1 - t1
        policiesPatch[name] = {
          tier_shift: shift,
          order_by: p.order_by,
        }
      })

      const patch = {
        default_policy: draft.default_policy,
        t1_max: baseT1,
        t2_max: baseT2,
        policies: policiesPatch,
      }

      await updateAdminConfig(patch)
      await load()
      setMsg({ ok: true, text: 'Đã lưu và áp dụng cấu hình runtime thành công.' })
    } catch (e) {
      if (e.name === 'AdminAuthError') {
        setAuthError(true)
        setCfg(null)  // clear protected state on 401/403 (#222)
      } else {
        setMsg({ ok: false, text: e.message })
      }
    } finally {
      setSaving(false)
    }
  }

  function handleAdminKeySubmit(ev) {
    ev.preventDefault()
    if (!adminKeyInput.trim()) return
    sessionStorage.setItem('sr_admin_key', adminKeyInput.trim())
    setAdminKeyInput('')
    load()
  }

  // Re-auth gate: show credential form instead of protected content (#222)
  if (authError) {
    return (
      <div className="flex flex-col h-full items-center justify-center p-6">
        <form onSubmit={handleAdminKeySubmit} className="bg-white border border-zinc-200 rounded-2xl p-6 shadow-sm w-full max-w-sm space-y-4">
          <div>
            <h2 className="text-sm font-semibold text-zinc-900">Cần Admin Key hợp lệ</h2>
            <p className="text-xs text-zinc-500 mt-1">Nhập admin key để truy cập cấu hình.</p>
          </div>
          <label className="block text-xs font-medium text-zinc-700">
            Admin Key
            <input
              type="password"
              value={adminKeyInput}
              onChange={e => setAdminKeyInput(e.target.value)}
              autoFocus
              placeholder="Nhập admin key..."
              className="mt-1.5 w-full rounded-xl border border-zinc-200 px-3 py-2 text-xs focus:outline-none focus:ring-1 focus:ring-zinc-400"
            />
          </label>
          <button
            type="submit"
            disabled={!adminKeyInput.trim()}
            className="w-full rounded-full bg-zinc-900 hover:bg-zinc-800 disabled:opacity-40 text-white text-xs font-semibold py-2.5 transition-colors"
          >
            Đăng nhập lại
          </button>
        </form>
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full overflow-hidden bg-white">
      {/* Header */}
      <header className="px-4 sm:px-6 py-3 sm:py-4 bg-white border-b border-zinc-100 flex items-center justify-between flex-none">
        <div className="flex items-center gap-3">
          <span className="text-sm font-bold text-zinc-900 tracking-tight">
            Portfolio &amp; Policy Routing
          </span>
          <span className="text-xs text-zinc-400 hidden sm:inline">
            Cấu hình ngưỡng phân tier và chính sách định tuyến model (Hot-reload)
          </span>
        </div>
      </header>

      {/* Main Content */}
      <div className="flex-1 overflow-y-auto p-3 sm:p-6 flex flex-col items-center touch-scroll">
        {loading ? (
          <div className="flex items-center justify-center h-48">
            <p className="text-sm text-zinc-400 animate-pulse">Đang tải cấu hình...</p>
          </div>
        ) : !cfg ? (
          <div className="flex flex-col items-center justify-center h-48 gap-3">
            <p className="text-sm text-rose-600">{msg?.text || 'Không thể tải cấu hình.'}</p>
            <button
              type="button"
              onClick={load}
              className="px-4 py-1.5 bg-zinc-900 text-white text-xs font-semibold rounded-full hover:bg-zinc-800 transition-colors"
            >
              Thử lại
            </button>
          </div>
        ) : (
          <div className="max-w-4xl w-full mx-auto space-y-4 sm:space-y-5">
            {/* Table Card */}
            <div className="bg-white border border-zinc-200/90 rounded-2xl shadow-xs overflow-hidden">
              <div className="px-4 sm:px-5 py-3.5 sm:py-4 border-b border-zinc-100 flex flex-col items-center text-center bg-zinc-50/50">
                <h2 className="text-sm font-semibold text-zinc-900">Bảng cấu hình Policy &amp; Ngưỡng Tier</h2>
                <p className="text-xs text-zinc-500 mt-0.5 max-w-xl">
                  Click dòng để chọn Policy mặc định. Bạn có thể tự do chỉnh sửa trực tiếp ngưỡng <span className="font-mono text-zinc-700 font-medium">T1_max</span> và <span className="font-mono text-zinc-700 font-medium">T2_max</span> của từng policy.
                </p>
              </div>

              <div className="overflow-x-auto touch-scroll">
                <table className="w-full min-w-[620px] text-left text-sm border-collapse">
                  <thead>
                    <tr className="bg-zinc-50/80 text-zinc-400 text-xs uppercase tracking-wider border-b border-zinc-200/80">
                      <th className="py-3 px-4 w-14 text-center">Chọn</th>
                      <th className="py-3 px-4 font-semibold text-center">Policy</th>
                      <th className="py-3 px-4 font-semibold w-48 text-center">Ngưỡng T1 (EASY)</th>
                      <th className="py-3 px-4 font-semibold w-48 text-center">Ngưỡng T2 (MEDIUM)</th>
                      <th className="py-3 px-4 font-semibold text-center">Chiến lược Fallback</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-zinc-100">
                    {Object.entries(cfg.policies || {}).map(([name, rule]) => {
                      const isActive = draft.default_policy === name
                      const pDraft = draft.policies[name] || { t1_max: 30, t2_max: 60 }
                      const meta = POLICY_META[name] || {
                        label: name,
                        tag: 'Tùy chỉnh',
                        desc: `order_by: ${rule.order_by}`,
                        orderBadge: { text: rule.order_by, icon: '⚙️', bg: 'bg-zinc-50 text-zinc-700 border-zinc-200' },
                      }

                      return (
                        <tr
                          key={name}
                          onClick={() => setDraft(d => ({ ...d, default_policy: name }))}
                          className={`transition-colors cursor-pointer group ${
                            isActive ? 'bg-zinc-100/70 hover:bg-zinc-100' : 'hover:bg-zinc-50/80'
                          }`}
                        >
                          {/* Radio Select */}
                          <td className="py-3.5 px-4 text-center" onClick={e => e.stopPropagation()}>
                            <input
                              type="radio"
                              name="default_policy"
                              checked={isActive}
                              onChange={() => setDraft(d => ({ ...d, default_policy: name }))}
                              className="w-4 h-4 text-zinc-900 border-zinc-300 focus:ring-zinc-900 cursor-pointer"
                            />
                          </td>

                          {/* Policy Name & Info */}
                          <td className="py-3.5 px-4">
                            <div className="flex items-center gap-2">
                              <span className="font-semibold text-zinc-900 text-sm">{meta.label}</span>
                              <span className="text-[10px] uppercase font-bold tracking-wider px-2 py-0.5 rounded-full bg-zinc-100 text-zinc-600 border border-zinc-200/80">
                                {meta.tag}
                              </span>
                              {isActive && (
                                <span className="text-[10px] font-bold text-zinc-900 bg-zinc-200/80 px-2 py-0.5 rounded-full">
                                  Default
                                </span>
                              )}
                            </div>
                            <p className="text-xs text-zinc-500 mt-0.5 line-clamp-1">{meta.desc}</p>
                          </td>

                          {/* T1 Threshold */}
                          <td className="py-3.5 px-4 text-center" onClick={e => e.stopPropagation()}>
                            <div className="flex items-center justify-center gap-1.5">
                              <span className="text-xs text-zinc-400 font-mono">&lt;</span>
                              <input
                                type="number"
                                min={1}
                                max={99}
                                value={pDraft.t1_max}
                                onChange={e => handleThresholdChange(name, 't1_max', e.target.value)}
                                className="w-20 px-2.5 py-1 text-sm font-semibold font-mono text-zinc-900 border border-zinc-200 rounded-full focus:outline-none focus:ring-1 focus:ring-zinc-400 bg-white text-center shadow-2xs"
                              />
                              <span className="text-[11px] text-zinc-400 font-normal">điểm</span>
                            </div>
                          </td>

                          {/* T2 Threshold */}
                          <td className="py-3.5 px-4 text-center" onClick={e => e.stopPropagation()}>
                            <div className="flex items-center justify-center gap-1.5">
                              <span className="text-xs text-zinc-400 font-mono">&lt;</span>
                              <input
                                type="number"
                                min={2}
                                max={100}
                                value={pDraft.t2_max}
                                onChange={e => handleThresholdChange(name, 't2_max', e.target.value)}
                                className="w-20 px-2.5 py-1 text-sm font-semibold font-mono text-zinc-900 border border-zinc-200 rounded-full focus:outline-none focus:ring-1 focus:ring-zinc-400 bg-white text-center shadow-2xs"
                              />
                              <span className="text-[11px] text-zinc-400 font-normal">điểm</span>
                            </div>
                          </td>

                          {/* Strategy Badge */}
                          <td className="py-3.5 px-4">
                            <div className="flex items-center justify-center">
                              <span
                                className={`inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-full border font-medium ${
                                  meta.orderBadge.bg
                                }`}
                              >
                                <span>{meta.orderBadge.icon}</span>
                                {meta.orderBadge.text}
                              </span>
                            </div>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>

              {/* Table Footer Actions */}
              <div className="px-5 py-3.5 bg-zinc-50/50 border-t border-zinc-100 flex flex-wrap items-center justify-between gap-3">
                <div className="flex items-center gap-2">
                  {!isValid ? (
                    <span className="text-xs text-rose-600 font-medium flex items-center gap-1">
                      ⚠️ {validationErrors[0]}
                    </span>
                  ) : msg ? (
                    <span
                      className={`text-xs font-medium flex items-center gap-1.5 ${
                        msg.ok ? 'text-emerald-600' : 'text-rose-600'
                      }`}
                    >
                      {msg.ok ? '✓' : '⚠️'} {msg.text}
                    </span>
                  ) : hasChanges ? (
                    <span className="text-xs text-amber-600 font-medium">
                      ● Đang có thay đổi chưa lưu
                    </span>
                  ) : (
                    <span className="text-xs text-zinc-400">
                      Cấu hình đồng bộ với máy chủ
                    </span>
                  )}
                </div>

                <div className="flex items-center gap-2.5 ml-auto">
                  <button
                    type="button"
                    onClick={handleRestoreDefaults}
                    disabled={saving}
                    className="px-3.5 py-1.5 text-xs font-medium text-zinc-700 hover:text-zinc-950 hover:bg-zinc-100 border border-zinc-200 rounded-full transition-colors flex items-center gap-1.5 shadow-xs"
                  >
                    <svg className="w-3.5 h-3.5 text-zinc-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                    </svg>
                    Khôi phục mặc định
                  </button>
                  {hasChanges && (
                    <button
                      type="button"
                      onClick={handleReset}
                      disabled={saving}
                      className="px-3.5 py-1.5 text-xs font-medium text-zinc-600 hover:text-zinc-900 rounded-full transition-colors"
                    >
                      Hoàn tác
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={handleSave}
                    disabled={saving || !hasChanges || !isValid}
                    className="px-4 py-1.5 bg-zinc-900 text-white text-xs font-semibold rounded-full hover:bg-zinc-800 transition-colors shadow-xs disabled:opacity-30 disabled:cursor-not-allowed flex items-center gap-1.5"
                  >
                    {saving && (
                      <svg className="w-3.5 h-3.5 animate-spin" fill="none" viewBox="0 0 24 24">
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
                      </svg>
                    )}
                    {saving ? 'Đang lưu...' : 'Lưu thay đổi'}
                  </button>
                </div>
              </div>
            </div>

            {/* Quick summary note */}
            <div className="px-4 py-3 rounded-2xl bg-zinc-50 border border-zinc-200/70 text-xs text-zinc-500 leading-relaxed text-center shadow-2xs">
              💡 <strong>Gợi ý quy tắc định tuyến:</strong> Điểm phân loại (&lt; T1) → <strong>Tier 1 (Flash / Rẻ nhất)</strong> | (&ge; T1 và &lt; T2) → <strong>Tier 2 (Mini / Cân bằng)</strong> | (&ge; T2) → <strong>Tier 3 (Sonnet / Cao cấp)</strong>. Bạn có thể tùy chỉnh ngưỡng riêng cho từng policy và bấm Lưu để áp dụng ngay.
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
