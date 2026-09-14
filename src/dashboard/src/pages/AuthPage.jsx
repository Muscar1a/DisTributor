import { useState } from 'react'
import { login, register } from '../api'

const DisTributorIcon = ({ className = "w-7 h-7" }) => (
  <svg className={className} viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
    <path
      d="M8 6h11l5 5v10l-5 5H8V6zm4 4v12h7l2-2v-8l-2-2h-7z"
      fill="currentColor"
      fillRule="evenodd"
    />
    <path
      d="M3 16h10"
      stroke="currentColor"
      strokeWidth="2.5"
      strokeLinecap="round"
    />
    <path
      d="M13 16l15-6M13 16h16M13 16l15 6"
      stroke="currentColor"
      strokeWidth="2.5"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
)

export default function AuthPage({ initialTab = 'login', onBack, onAuthSuccess }) {
  const [tab, setTab] = useState(initialTab)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [fullName, setFullName] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function handleSubmit(e) {
    e.preventDefault()
    setError('')

    const cleanEmail = email.trim().toLowerCase()
    const emailRegex = /^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$/
    if (!emailRegex.test(cleanEmail)) {
      setError('Email không đúng định dạng hợp lệ.')
      return
    }

    if (password.length < 8) {
      setError('Mật khẩu phải có ít nhất 8 ký tự.')
      return
    }

    if (password.length > 72) {
      setError('Mật khẩu không được vượt quá 72 ký tự.')
      return
    }

    setBusy(true)
    try {
      let res
      if (tab === 'login') {
        res = await login(cleanEmail, password)
      } else {
        const cleanName = fullName.trim().replace(/<[^>]*>?/gm, '')
        res = await register(cleanEmail, password, cleanName || null)
      }
      if (res?.user) {
        onAuthSuccess(res.user)
      }
    } catch (err) {
      setError(err.message || 'Đã có lỗi xảy ra.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="min-h-screen bg-[#F5F6F8] font-sans antialiased text-zinc-900 flex flex-col justify-between">
      {/* ─── Top Bar ────────────────────────────────────────────────────────── */}
      <header className="w-full max-w-6xl mx-auto px-4 sm:px-6 py-5 flex items-center justify-between">
        <button
          type="button"
          onClick={onBack}
          className="flex items-center gap-2.5 text-left group cursor-pointer"
        >
          <div className="w-8 h-8 rounded-xl bg-white border border-zinc-200/80 shadow-2xs flex items-center justify-center text-zinc-900 group-hover:bg-zinc-100 transition-colors">
            <DisTributorIcon className="w-5 h-5 text-zinc-900" />
          </div>
          <div className="flex flex-col">
            <span className="text-sm font-bold tracking-tight text-zinc-900 leading-tight">DisTributor</span>
            <span className="text-[9px] text-zinc-400 font-medium tracking-wider uppercase">LLM Router</span>
          </div>
        </button>

        <button
          type="button"
          onClick={onBack}
          className="inline-flex items-center gap-1.5 text-xs font-semibold text-zinc-500 hover:text-zinc-900 px-3.5 py-1.5 rounded-full hover:bg-zinc-200/60 transition-colors cursor-pointer"
        >
          <svg className="w-3.5 h-3.5 stroke-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" d="M10.5 19.5L3 12m0 0l7.5-7.5M3 12h18" />
          </svg>
          <span>Quay lại trang chủ</span>
        </button>
      </header>

      {/* ─── Main Content ────────────────────────────────────────────────────── */}
      <main className="flex-1 flex items-center justify-center px-4 py-8 sm:py-12">
        <div className="w-full max-w-md bg-white rounded-3xl border border-zinc-200/90 shadow-xl p-7 sm:p-9 relative animate-fadeIn">
          {/* Header */}
          <div className="text-center mb-6">
            <div className="w-12 h-12 bg-zinc-900 text-white rounded-2xl flex items-center justify-center mx-auto mb-3 shadow-sm">
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
              </svg>
            </div>
            <h1 className="text-xl sm:text-2xl font-bold tracking-tight text-zinc-900">
              {tab === 'login' ? 'Đăng nhập DisTributor' : 'Đăng ký tài khoản'}
            </h1>
            <p className="text-xs text-zinc-500 mt-1.5 max-w-xs mx-auto">
              {tab === 'login'
                ? 'Đăng nhập để vào ứng dụng và áp dụng cấu hình định tuyến cá nhân hóa'
                : 'Tạo tài khoản để sở hữu API key cá nhân và cấu hình routing riêng'}
            </p>
          </div>

          {/* Segmented Tab Switcher */}
          <div className="flex bg-zinc-100 p-1 rounded-xl mb-6">
            <button
              type="button"
              onClick={() => { setTab('login'); setError('') }}
              className={`flex-1 py-2 text-xs font-semibold rounded-lg transition-all cursor-pointer ${
                tab === 'login'
                  ? 'bg-white text-zinc-900 shadow-xs'
                  : 'text-zinc-500 hover:text-zinc-800'
              }`}
            >
              Đăng nhập
            </button>
            <button
              type="button"
              onClick={() => { setTab('register'); setError('') }}
              className={`flex-1 py-2 text-xs font-semibold rounded-lg transition-all cursor-pointer ${
                tab === 'register'
                  ? 'bg-white text-zinc-900 shadow-xs'
                  : 'text-zinc-500 hover:text-zinc-800'
              }`}
            >
              Đăng ký
            </button>
          </div>

          {/* Error alert */}
          {error && (
            <div className="mb-5 p-3.5 bg-rose-50 border border-rose-200 text-rose-700 text-xs rounded-xl flex items-center gap-2">
              <svg className="w-4 h-4 shrink-0 text-rose-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
              </svg>
              <span>{error}</span>
            </div>
          )}

          {/* Form */}
          <form onSubmit={handleSubmit} className="space-y-4">
            {tab === 'register' && (
              <div>
                <label className="block text-xs font-semibold text-zinc-700 mb-1.5">
                  Họ và tên / Nickname
                </label>
                <input
                  type="text"
                  required
                  placeholder="Ví dụ: Alice Nguyen"
                  value={fullName}
                  onChange={(e) => setFullName(e.target.value)}
                  className="w-full px-3.5 py-2.5 bg-zinc-50 border border-zinc-200 rounded-xl text-xs text-zinc-900 focus:outline-none focus:ring-2 focus:ring-zinc-900 focus:bg-white transition-all placeholder:text-zinc-400"
                />
              </div>
            )}

            <div>
              <label className="block text-xs font-semibold text-zinc-700 mb-1.5">
                Email Developer
              </label>
              <input
                type="email"
                required
                placeholder="developer@example.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="w-full px-3.5 py-2.5 bg-zinc-50 border border-zinc-200 rounded-xl text-xs text-zinc-900 focus:outline-none focus:ring-2 focus:ring-zinc-900 focus:bg-white transition-all placeholder:text-zinc-400"
              />
            </div>

            <div>
              <label className="block text-xs font-semibold text-zinc-700 mb-1.5">
                Mật khẩu
              </label>
              <input
                type="password"
                required
                placeholder="Tối thiểu 6 ký tự"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full px-3.5 py-2.5 bg-zinc-50 border border-zinc-200 rounded-xl text-xs text-zinc-900 focus:outline-none focus:ring-2 focus:ring-zinc-900 focus:bg-white transition-all placeholder:text-zinc-400"
              />
            </div>

            <button
              type="submit"
              disabled={busy}
              className="w-full mt-2 py-3 px-4 bg-zinc-900 hover:bg-zinc-800 disabled:bg-zinc-400 text-white font-semibold text-xs rounded-xl shadow-xs transition-all active:scale-98 flex items-center justify-center gap-2 cursor-pointer"
            >
              {busy ? (
                <>
                  <svg className="w-4 h-4 animate-spin text-white" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
                  </svg>
                  <span>Đang xử lý...</span>
                </>
              ) : tab === 'login' ? (
                <span>Đăng nhập vào ứng dụng</span>
              ) : (
                <span>Hoàn tất đăng ký &amp; Vào ứng dụng</span>
              )}
            </button>
          </form>

          {/* Alternate Tab Prompt */}
          <div className="mt-6 pt-5 border-t border-zinc-100 text-center text-xs text-zinc-500">
            {tab === 'login' ? (
              <p>
                Chưa có tài khoản?{' '}
                <button
                  type="button"
                  onClick={() => { setTab('register'); setError('') }}
                  className="text-zinc-900 font-bold hover:underline cursor-pointer ml-1"
                >
                  Đăng ký ngay
                </button>
              </p>
            ) : (
              <p>
                Đã có tài khoản?{' '}
                <button
                  type="button"
                  onClick={() => { setTab('login'); setError('') }}
                  className="text-zinc-900 font-bold hover:underline cursor-pointer ml-1"
                >
                  Đăng nhập
                </button>
              </p>
            )}
          </div>
        </div>
      </main>

      {/* ─── Minimal Footer ─────────────────────────────────────────────────── */}
      <footer className="py-6 px-4 text-center text-xs text-zinc-400">
        <span>DisTributor Gateway · Smart LLM Routing</span>
      </footer>
    </div>
  )
}
