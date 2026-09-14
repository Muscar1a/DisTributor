import { useState, useEffect } from 'react'
import {
  getMe,
  updatePreferences,
  fetchUserKeys,
  createUserKey,
  revokeUserKey,
} from '../api'

export default function Settings({ user, onAuthRequired, onUserUpdated }) {
  const [preferences, setPreferences] = useState({
    default_policy: 'balanced',
    default_classifier_version: 'v1.5',
    budget_monthly_usd: '',
  })
  const [keys, setKeys] = useState([])
  const [keyName, setKeyName] = useState('')
  const [rateLimit, setRateLimit] = useState(60)
  const [createdKey, setCreatedKey] = useState('')
  const [savingPrefs, setSavingPrefs] = useState(false)
  const [prefMessage, setPrefMessage] = useState('')
  const [keyError, setKeyError] = useState('')
  const [busyKey, setBusyKey] = useState(false)

  useEffect(() => {
    if (user) {
      if (user.preferences) {
        setPreferences({
          default_policy: user.preferences.default_policy || 'balanced',
          default_classifier_version: user.preferences.default_classifier_version || 'v1.5',
          budget_monthly_usd: user.preferences.budget_monthly_usd ?? '',
        })
      }
      loadKeys()
    }
  }, [user])

  async function loadKeys() {
    try {
      const data = await fetchUserKeys()
      setKeys(data.items || [])
    } catch {
      // Ignored if not authenticated
    }
  }

  async function handleSavePreferences(e) {
    e.preventDefault()
    setSavingPrefs(true)
    setPrefMessage('')
    try {
      const payload = {
        default_policy: preferences.default_policy,
        default_classifier_version: preferences.default_classifier_version,
      }
      if (preferences.budget_monthly_usd !== '') {
        payload.budget_monthly_usd = parseFloat(preferences.budget_monthly_usd)
      }
      const res = await updatePreferences(payload)
      setPrefMessage('Cập nhật cấu hình định tuyến thành công!')
      if (onUserUpdated) {
        const freshUser = await getMe()
        if (freshUser?.user) onUserUpdated(freshUser.user)
      }
    } catch (err) {
      setPrefMessage(`Lỗi: ${err.message}`)
    } finally {
      setSavingPrefs(false)
    }
  }

  async function handleCreateKey(e) {
    e.preventDefault()
    if (!keyName.trim()) return
    setBusyKey(true)
    setKeyError('')
    setCreatedKey('')
    try {
      const created = await createUserKey(keyName.trim(), Number(rateLimit))
      setCreatedKey(created.key)
      setKeyName('')
      await loadKeys()
    } catch (err) {
      setKeyError(err.message)
    } finally {
      setBusyKey(false)
    }
  }

  async function handleRevokeKey(keyItem) {
    if (!window.confirm(`Thu hồi API Key "${keyItem.name}"? Hành động này không thể hoàn tác.`)) return
    try {
      await revokeUserKey(keyItem.id)
      await loadKeys()
    } catch (err) {
      alert(`Lỗi thu hồi key: ${err.message}`)
    }
  }

  if (!user) {
    return (
      <div className="flex-1 overflow-y-auto bg-white p-6">
        <div className="max-w-2xl mx-auto text-center py-16">
          <div className="w-16 h-16 bg-zinc-100 rounded-full flex items-center justify-center mx-auto mb-4 text-zinc-400">
            <svg className="w-8 h-8" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
            </svg>
          </div>
          <h2 className="text-xl font-bold text-zinc-900 mb-2">Cá nhân hóa trải nghiệm</h2>
          <p className="text-zinc-500 text-sm mb-6">
            Đăng nhập để thiết lập chính sách định tuyến mặc định (Tiết kiệm chi phí / Chất lượng cao) và quản lý API Key cá nhân của bạn.
          </p>
          <button
            onClick={onAuthRequired}
            className="px-5 py-2.5 bg-zinc-900 hover:bg-zinc-800 text-white text-sm font-medium rounded-xl shadow-xs transition-colors"
          >
            Đăng nhập hoặc Đăng ký
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="flex-1 overflow-y-auto bg-white p-4 sm:p-6 md:p-8 touch-scroll">
      <div className="max-w-4xl mx-auto space-y-8">
        {/* Header */}
        <div>
          <h1 className="text-xl font-bold tracking-tight text-zinc-900">Cài đặt Cá nhân hóa</h1>
          <p className="text-xs text-zinc-500 mt-1">
            Tài khoản: <span className="font-semibold text-zinc-700">{user.email}</span>
            {user.full_name && ` (${user.full_name})`}
          </p>
        </div>

        {/* Form: Routing Preferences */}
        <section className="bg-zinc-50/70 border border-zinc-200/80 rounded-2xl p-5 sm:p-6 space-y-6">
          <div>
            <h2 className="text-base font-semibold text-zinc-900">Chính sách định tuyến mặc định (Default Policy)</h2>
            <p className="text-xs text-zinc-500 mt-0.5">
              Khi gọi API từ code mà không truyền tham số <code className="text-zinc-700 font-mono">smartroute.policy</code>, gateway sẽ áp dụng chính sách bạn chọn dưới đây.
            </p>
          </div>

          <form onSubmit={handleSavePreferences} className="space-y-5">
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              {/* Balanced */}
              <label
                className={`flex flex-col p-4 rounded-xl border cursor-pointer transition-all ${
                  preferences.default_policy === 'balanced'
                    ? 'border-zinc-900 bg-white shadow-xs'
                    : 'border-zinc-200 bg-white/50 hover:bg-white'
                }`}
              >
                <div className="flex items-center justify-between mb-2">
                  <span className="text-sm font-semibold text-zinc-900">Cân bằng</span>
                  <input
                    type="radio"
                    name="policy"
                    value="balanced"
                    checked={preferences.default_policy === 'balanced'}
                    onChange={e => setPreferences(prev => ({ ...prev, default_policy: e.target.value }))}
                    className="accent-zinc-900"
                  />
                </div>
                <p className="text-xs text-zinc-500">
                  Tối ưu giữa chi phí và chất lượng. Dùng tier phù hợp nhất cho từng câu hỏi.
                </p>
              </label>

              {/* Cost-first */}
              <label
                className={`flex flex-col p-4 rounded-xl border cursor-pointer transition-all ${
                  preferences.default_policy === 'cost-first'
                    ? 'border-zinc-900 bg-white shadow-xs'
                    : 'border-zinc-200 bg-white/50 hover:bg-white'
                }`}
              >
                <div className="flex items-center justify-between mb-2">
                  <span className="text-sm font-semibold text-zinc-900">Tiết kiệm (Cost-First)</span>
                  <input
                    type="radio"
                    name="policy"
                    value="cost-first"
                    checked={preferences.default_policy === 'cost-first'}
                    onChange={e => setPreferences(prev => ({ ...prev, default_policy: e.target.value }))}
                    className="accent-zinc-900"
                  />
                </div>
                <p className="text-xs text-zinc-500">
                  Ưu tiên model chi phí thấp nhất trong tier để tối đa hóa ngân sách.
                </p>
              </label>

              {/* Quality-first */}
              <label
                className={`flex flex-col p-4 rounded-xl border cursor-pointer transition-all ${
                  preferences.default_policy === 'quality-first'
                    ? 'border-zinc-900 bg-white shadow-xs'
                    : 'border-zinc-200 bg-white/50 hover:bg-white'
                }`}
              >
                <div className="flex items-center justify-between mb-2">
                  <span className="text-sm font-semibold text-zinc-900">Chất lượng (Quality-First)</span>
                  <input
                    type="radio"
                    name="policy"
                    value="quality-first"
                    checked={preferences.default_policy === 'quality-first'}
                    onChange={e => setPreferences(prev => ({ ...prev, default_policy: e.target.value }))}
                    className="accent-zinc-900"
                  />
                </div>
                <p className="text-xs text-zinc-500">
                  Ưu tiên model mạnh nhất để đảm bảo độ chính xác cao nhất cho tác vụ.
                </p>
              </label>
            </div>

            {/* Classifier Version */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 pt-2">
              <div>
                <label className="block text-xs font-semibold text-zinc-700 mb-1">
                  Classifier Version
                </label>
                <select
                  value={preferences.default_classifier_version}
                  onChange={e => setPreferences(prev => ({ ...prev, default_classifier_version: e.target.value }))}
                  className="w-full text-xs bg-white border border-zinc-200 rounded-xl px-3 py-2 text-zinc-800 focus:outline-none focus:border-zinc-400"
                >
                  <option value="v1.5">v1.5 — Heuristic (Nhanh, &lt;5ms, zero latency)</option>
                  <option value="v2">v2 — LLM Scorer (Phân tích sâu ngữ nghĩa)</option>
                </select>
              </div>

              <div>
                <label className="block text-xs font-semibold text-zinc-700 mb-1">
                  Hạn mức chi tiêu tháng (USD, tùy chọn)
                </label>
                <input
                  type="number"
                  step="0.01"
                  placeholder="Không giới hạn"
                  value={preferences.budget_monthly_usd}
                  onChange={e => setPreferences(prev => ({ ...prev, budget_monthly_usd: e.target.value }))}
                  className="w-full text-xs bg-white border border-zinc-200 rounded-xl px-3 py-2 text-zinc-800 focus:outline-none focus:border-zinc-400"
                />
              </div>
            </div>

            <div className="flex items-center justify-between pt-2">
              <span className={`text-xs ${prefMessage.startsWith('Lỗi') ? 'text-rose-600' : 'text-emerald-600'}`}>
                {prefMessage}
              </span>
              <button
                type="submit"
                disabled={savingPrefs}
                className="px-4 py-2 bg-zinc-900 hover:bg-zinc-800 text-white text-xs font-medium rounded-xl shadow-xs transition-colors disabled:opacity-50"
              >
                {savingPrefs ? 'Đang lưu...' : 'Lưu cấu hình'}
              </button>
            </div>
          </form>
        </section>

        {/* Personal API Keys Section */}
        <section className="bg-zinc-50/70 border border-zinc-200/80 rounded-2xl p-5 sm:p-6 space-y-6">
          <div>
            <h2 className="text-base font-semibold text-zinc-900">API Key cá nhân của bạn</h2>
            <p className="text-xs text-zinc-500 mt-0.5">
              Dùng API Key này trong code của bạn để gọi gateway. Request sẽ tự động áp dụng cấu hình định tuyến cá nhân của bạn.
            </p>
          </div>

          {/* New Key Form */}
          <form onSubmit={handleCreateKey} className="flex flex-col sm:flex-row gap-3">
            <input
              type="text"
              placeholder="Tên key (ví dụ: Dev Project, Laptop...)"
              value={keyName}
              onChange={e => setKeyName(e.target.value)}
              className="flex-1 text-xs bg-white border border-zinc-200 rounded-xl px-3 py-2 text-zinc-800 focus:outline-none focus:border-zinc-400"
            />
            <div className="flex items-center gap-2">
              <label className="text-xs text-zinc-500 shrink-0">RPM:</label>
              <input
                type="number"
                min="1"
                max="1000"
                value={rateLimit}
                onChange={e => setRateLimit(e.target.value)}
                className="w-20 text-xs bg-white border border-zinc-200 rounded-xl px-3 py-2 text-zinc-800 focus:outline-none focus:border-zinc-400"
              />
            </div>
            <button
              type="submit"
              disabled={busyKey || !keyName.trim()}
              className="px-4 py-2 bg-zinc-900 hover:bg-zinc-800 text-white text-xs font-medium rounded-xl shadow-xs transition-colors disabled:opacity-50 shrink-0"
            >
              {busyKey ? 'Đang tạo...' : '+ Tạo Key'}
            </button>
          </form>

          {keyError && (
            <p className="text-xs text-rose-600">{keyError}</p>
          )}

          {createdKey && (
            <div className="p-4 bg-emerald-50 border border-emerald-200 rounded-xl space-y-2">
              <p className="text-xs font-semibold text-emerald-800">
                Key mới đã được tạo thành công! Hãy lưu lại ngay, bạn sẽ không thể xem lại:
              </p>
              <div className="flex items-center gap-2">
                <code className="text-xs bg-white border border-emerald-300 rounded px-2.5 py-1.5 font-mono text-zinc-800 flex-1 overflow-x-auto">
                  {createdKey}
                </code>
                <button
                  type="button"
                  onClick={() => {
                    navigator.clipboard.writeText(createdKey)
                    alert('Đã copy API Key vào clipboard!')
                  }}
                  className="px-3 py-1.5 bg-emerald-700 text-white text-xs rounded hover:bg-emerald-800 shrink-0"
                >
                  Copy
                </button>
              </div>
            </div>
          )}

          {/* Keys Table */}
          <div className="overflow-x-auto">
            <table className="w-full text-xs text-left">
              <thead>
                <tr className="border-b border-zinc-200 text-zinc-500">
                  <th className="pb-2 font-medium">Tên Key</th>
                  <th className="pb-2 font-medium">Key Masked</th>
                  <th className="pb-2 font-medium">Hạn mức RPM</th>
                  <th className="pb-2 font-medium">Trạng thái</th>
                  <th className="pb-2 font-medium text-right">Thao tác</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-200/60">
                {keys.length === 0 ? (
                  <tr>
                    <td colSpan={5} className="py-6 text-center text-zinc-400">
                      Chưa có API key cá nhân nào. Hãy tạo một key ở trên!
                    </td>
                  </tr>
                ) : (
                  keys.map(k => (
                    <tr key={k.id} className="text-zinc-700">
                      <td className="py-2.5 font-medium">{k.name}</td>
                      <td className="py-2.5 font-mono text-zinc-500">{k.key_masked}</td>
                      <td className="py-2.5">{k.rate_limit_per_min} RPM</td>
                      <td className="py-2.5">
                        <span className={`inline-flex px-2 py-0.5 rounded-full text-[10px] font-medium ${
                          k.active ? 'bg-emerald-100 text-emerald-800' : 'bg-zinc-200 text-zinc-600'
                        }`}>
                          {k.active ? 'Hoạt động' : 'Đã thu hồi'}
                        </span>
                      </td>
                      <td className="py-2.5 text-right">
                        {k.active && (
                          <button
                            type="button"
                            onClick={() => handleRevokeKey(k)}
                            className="text-rose-600 hover:text-rose-800 font-medium"
                          >
                            Thu hồi
                          </button>
                        )}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </div>
  )
}
