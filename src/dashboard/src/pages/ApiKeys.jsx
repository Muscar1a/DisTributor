import { useEffect, useState } from 'react'
import { AdminAuthError, createApiKey, fetchApiKeys, revokeApiKey } from '../api'

export default function ApiKeys() {
  const [adminKey, setAdminKey] = useState('')
  const [keys, setKeys] = useState([])
  const [name, setName] = useState('')
  const [rateLimit, setRateLimit] = useState(60)
  const [createdKey, setCreatedKey] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function loadKeys() {
    setError('')
    try {
      const data = await fetchApiKeys(adminKey)
      setKeys(data.items || [])
    } catch (err) {
      if (err instanceof AdminAuthError) {
        setKeys([])  // clear protected rows on auth failure (#222)
      }
      setError(err.message)
    }
  }

  useEffect(() => { loadKeys() }, [])

  async function submit(event) {
    event.preventDefault()
    setBusy(true)
    setError('')
    setCreatedKey('')
    try {
      const created = await createApiKey(adminKey, name.trim(), Number(rateLimit))
      setCreatedKey(created.key)
      setName('')
      await loadKeys()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  async function revoke(key) {
    if (!window.confirm(`Revoke API key ?${key.name}?? This cannot be undone.`)) return
    setError('')
    try {
      await revokeApiKey(adminKey, key.id)
      await loadKeys()
    } catch (err) {
      setError(err.message)
    }
  }

  return (
    <div className="flex-1 overflow-y-auto bg-white p-3 sm:p-5 md:p-6 touch-scroll">
      <div className="max-w-6xl mx-auto space-y-4 sm:space-y-6">
        <header>
          <h1 className="text-lg sm:text-xl font-bold tracking-tight text-zinc-900">Invest &amp; API Keys</h1>
          <p className="text-xs text-zinc-400 mt-0.5 sm:mt-1">Quản lý và cấp phát mã khóa kết nối API cho gateway.</p>
        </header>

        <div className="grid lg:grid-cols-[320px_minmax(0,1fr)] gap-4 sm:gap-5 items-start">
          <form onSubmit={submit} className="bg-white border border-zinc-200/90 rounded-2xl p-4 sm:p-5 shadow-xs space-y-4">
            <div>
              <h2 className="font-semibold text-zinc-900 text-sm">Tạo API Key mới</h2>
              <p className="text-xs text-zinc-400 mt-0.5">Mã bí mật sẽ chỉ hiển thị một lần duy nhất.</p>
            </div>
            <label className="block text-xs font-medium text-zinc-700">
              Admin key
              <input
                type="password"
                value={adminKey}
                onChange={event => setAdminKey(event.target.value)}
                placeholder="Yêu cầu khi ADMIN_KEY được đặt"
                className="mt-1.5 w-full rounded-xl border border-zinc-200 px-3 py-2 text-xs focus:outline-none focus:ring-1 focus:ring-zinc-400"
              />
            </label>
            <label className="block text-xs font-medium text-zinc-700">
              Tên định danh (Name)
              <input
                value={name}
                onChange={event => setName(event.target.value)}
                placeholder="app-web"
                maxLength={255}
                required
                className="mt-1.5 w-full rounded-xl border border-zinc-200 px-3 py-2 text-xs focus:outline-none focus:ring-1 focus:ring-zinc-400"
              />
            </label>
            <label className="block text-xs font-medium text-zinc-700">
              Giới hạn lượt (RPM)
              <input
                type="number"
                min="1"
                max="1000"
                value={rateLimit}
                onChange={event => setRateLimit(event.target.value)}
                required
                className="mt-1.5 w-full rounded-xl border border-zinc-200 px-3 py-2 text-xs focus:outline-none focus:ring-1 focus:ring-zinc-400"
              />
            </label>
            <button
              disabled={busy}
              className="w-full rounded-full bg-zinc-900 hover:bg-zinc-800 disabled:opacity-40 text-white text-xs font-semibold py-2.5 transition-colors shadow-xs cursor-pointer"
            >
              {busy ? 'Đang tạo…' : '+ Tạo Key'}
            </button>
          </form>

          <section className="bg-white border border-zinc-200/90 rounded-2xl p-4 sm:p-5 shadow-xs min-w-0">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h2 className="font-semibold text-zinc-900 text-sm">Danh sách Gateway Keys</h2>
                <p className="text-xs text-zinc-400 mt-0.5">Tổng số request đã định tuyến qua từng key.</p>
              </div>
              <button
                onClick={loadKeys}
                className="text-xs font-semibold border border-zinc-200 rounded-full px-3.5 py-1.5 hover:bg-zinc-50 transition-colors shadow-2xs cursor-pointer"
              >
                Làm mới
              </button>
            </div>

            {createdKey && (
              <div role="status" className="mt-4 rounded-2xl border border-emerald-200 bg-emerald-50 p-4">
                <strong className="block text-xs font-bold text-emerald-900">Sao chép key của bạn ngay bây giờ:</strong>
                <div className="flex items-center gap-2 mt-2">
                  <code className="flex-1 text-xs break-all text-emerald-950 font-mono font-bold bg-white/80 px-2.5 py-1.5 rounded-lg border border-emerald-200">{createdKey}</code>
                  <button
                    onClick={() => navigator.clipboard.writeText(createdKey)}
                    className="text-xs bg-zinc-900 hover:bg-zinc-800 text-white font-medium rounded-full px-3.5 py-1.5 transition-colors shadow-xs cursor-pointer"
                  >
                    Copy
                  </button>
                </div>
              </div>
            )}
            {error && <p role="alert" className="mt-4 text-xs text-rose-600 font-medium">{error}</p>}

            <div className="overflow-x-auto touch-scroll mt-4">
              <table className="w-full min-w-[550px] text-sm">
                <thead>
                  <tr className="text-left text-xs uppercase tracking-wider text-zinc-400 border-b border-zinc-100">
                    <th className="py-3 pr-4">Name</th>
                    <th className="py-3 pr-4">Key</th>
                    <th className="py-3 pr-4">Status</th>
                    <th className="py-3 pr-4">RPM</th>
                    <th className="py-3 pr-4">Requests</th>
                    <th className="py-3 pr-4">Created</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {keys.map(key => (
                    <tr key={key.id} className="border-b border-zinc-100 last:border-0 hover:bg-zinc-50/60 transition-colors">
                      <td className="py-3 pr-4 font-medium text-zinc-900">{key.name}</td>
                      <td className="py-3 pr-4"><code className="text-xs font-mono text-zinc-600 bg-zinc-100 px-1.5 py-0.5 rounded">{key.key_masked}</code></td>
                      <td className="py-3 pr-4">
                        <span className={`text-xs font-semibold rounded-full px-2.5 py-0.5 border ${
                          key.active
                            ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
                            : 'bg-rose-50 text-rose-700 border-rose-200'
                        }`}>
                          {key.active ? 'Active' : 'Revoked'}
                        </span>
                      </td>
                      <td className="py-3 pr-4 text-xs text-zinc-700">{key.rate_limit_per_min}</td>
                      <td className="py-3 pr-4 text-xs font-mono text-zinc-700">{key.total_requests || 0}</td>
                      <td className="py-3 pr-4 whitespace-nowrap text-xs text-zinc-400">{new Date(key.created_at).toLocaleDateString()}</td>
                      <td className="py-3 text-right">
                        {key.active && (
                          <button
                            onClick={() => revoke(key)}
                            className="text-xs font-medium text-rose-600 hover:text-rose-800 transition-colors underline"
                          >
                            Revoke
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {!keys.length && <p className="py-10 text-center text-xs text-zinc-400">Chưa có API key nào.</p>}
            </div>
          </section>
        </div>
      </div>
    </div>
  )
}
