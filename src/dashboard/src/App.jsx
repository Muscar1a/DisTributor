import { useState, useEffect, useRef, useLayoutEffect } from 'react'
import { checkHealth } from './api'
import ConfigPanel from './pages/ConfigPanel'
import Playground from './pages/Playground'
import StatsPage from './pages/StatsPage'
import ApiKeys from './pages/ApiKeys'
import RequestLogs from './pages/RequestLogs'
import LandingPage from './pages/LandingPage'

// ─── Minimal Fine-line Icons (Origin Style) ──────────────────────────────────

const DisTributorIcon = ({ className = "w-8 h-8" }) => (
  <svg className={className} viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
    {/* Geometric 'D' */}
    <path
      d="M8 6h11l5 5v10l-5 5H8V6zm4 4v12h7l2-2v-8l-2-2h-7z"
      fill="currentColor"
      fillRule="evenodd"
    />
    {/* Incoming Beam */}
    <path
      d="M3 16h10"
      stroke="currentColor"
      strokeWidth="2.5"
      strokeLinecap="round"
    />
    {/* 3 Outgoing Tier Rays (T1, T2, T3) */}
    <path
      d="M13 16l15-6M13 16h16M13 16l15 6"
      stroke="currentColor"
      strokeWidth="2.5"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
)

const BrandLogo = ({ onClick }) => (
  <div
    className={`flex items-center gap-3 px-4 py-5 select-none ${onClick ? 'cursor-pointer hover:opacity-80 transition-opacity' : ''}`}
    onClick={onClick}
    title={onClick ? "Quay về trang chủ" : undefined}
  >
    <div className="w-8 h-8 flex items-center justify-center text-zinc-900 shrink-0">
      <DisTributorIcon className="w-8 h-8 text-zinc-900" />
    </div>
    <div className="flex flex-col">
      <span className="text-base font-bold tracking-tight text-zinc-900 font-sans leading-none">DisTributor</span>
      <span className="text-[10px] text-zinc-400 font-medium tracking-wider uppercase mt-0.5">LLM Router</span>
    </div>
  </div>
)

const PlaygroundIcon = () => (
  <svg className="w-4 h-4 stroke-[1.75]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
    <path strokeLinecap="round" strokeLinejoin="round" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09zM18.259 8.715L18 9.75l-.259-1.035a3.375 3.375 0 00-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 002.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 002.456 2.456L21.75 6l-1.035.259a3.375 3.375 0 00-2.456 2.456z" />
  </svg>
)

const DashboardIcon = () => (
  <svg className="w-4 h-4 stroke-[1.75]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
    <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 6A2.25 2.25 0 016 3.75h2.25A2.25 2.25 0 0110.5 6v2.25a2.25 2.25 0 01-2.25 2.25H6a2.25 2.25 0 01-2.25-2.25V6zM3.75 15.75A2.25 2.25 0 016 13.5h2.25a2.25 2.25 0 012.25 2.25V18a2.25 2.25 0 01-2.25 2.25H6A2.25 2.25 0 013.75 18v-2.25zM13.5 6a2.25 2.25 0 012.25-2.25H18A2.25 2.25 0 0120.25 6v2.25A2.25 2.25 0 0118 10.5h-2.25a2.25 2.25 0 01-2.25-2.25V6zM13.5 15.75a2.25 2.25 0 012.25-2.25H18a2.25 2.25 0 012.25 2.25V18A2.25 2.25 0 0118 20.25h-2.25A2.25 2.25 0 0113.5 18v-2.25z" />
  </svg>
)

const LogsIcon = () => (
  <svg className="w-4 h-4 stroke-[1.75]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
    <path strokeLinecap="round" strokeLinejoin="round" d="M8.25 6.75h12M8.25 12h12m-12 5.25h12M3.75 6.75h.007v.008H3.75V6.75zm.375 0a.375.375 0 11-.75 0 .375.375 0 01.75 0zM3.75 12h.007v.008H3.75V12zm.375 0a.375.375 0 11-.75 0 .375.375 0 01.75 0zm-.375 5.25h.007v.008H3.75v-.008zm.375 0a.375.375 0 11-.75 0 .375.375 0 01.75 0z" />
  </svg>
)

const KeysIcon = () => (
  <svg className="w-4 h-4 stroke-[1.75]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
    <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 5.25a3 3 0 013 3m3 0a6 6 0 01-7.029 5.912c-.563-.097-1.159.026-1.563.43L10.5 17.25H8.25v2.25H6v2.25H2.25v-2.818c0-.597.237-1.17.659-1.591l6.499-6.499c.404-.404.527-1 .43-1.563A6 6 0 1121.75 8.25z" />
  </svg>
)

const ConfigIcon = () => (
  <svg className="w-4 h-4 stroke-[1.75]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
    <path strokeLinecap="round" strokeLinejoin="round" d="M10.5 6h9.75M10.5 6a1.5 1.5 0 11-3 0m3 0a1.5 1.5 0 10-3 0M3.75 6H7.5m3 12h9.75m-9.75 0a1.5 1.5 0 01-3 0m3 0a1.5 1.5 0 00-3 0m-3.75 0H7.5m9-6h3.75m-3.75 0a1.5 1.5 0 01-3 0m3 0a1.5 1.5 0 00-3 0m-9.75 0h9.75" />
  </svg>
)

const SettingsIcon = () => (
  <svg className="w-4 h-4 stroke-[1.75]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
    <path strokeLinecap="round" strokeLinejoin="round" d="M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.325.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 011.37.49l1.296 2.247a1.125 1.125 0 01-.26 1.431l-1.003.827c-.293.241-.438.613-.43.992a7.723 7.723 0 010 .255c-.008.378.137.75.43.991l1.004.827c.424.35.534.955.26 1.43l-1.298 2.247a1.125 1.125 0 01-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.47 6.47 0 01-.22.128c-.331.183-.581.495-.644.869l-.213 1.281c-.09.543-.56.94-1.11.94h-2.594c-.55 0-1.019-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 01-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 01-1.369-.49l-1.297-2.247a1.125 1.125 0 01.26-1.431l1.004-.827c.292-.24.437-.613.43-.991a6.932 6.932 0 010-.255c.007-.38-.138-.751-.43-.992l-1.004-.827a1.125 1.125 0 01-.26-1.43l1.297-2.247a1.125 1.125 0 011.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.086.22-.128.332-.183.582-.495.644-.869l.214-1.28Z" />
    <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
  </svg>
)

const NAV = [
  { id: 'playground', label: 'Playground',    Icon: PlaygroundIcon },
  { id: 'dashboard',  label: 'Dashboard',     Icon: DashboardIcon },
  { id: 'logs',       label: 'Request Logs',  Icon: LogsIcon },
  { id: 'keys',       label: 'API Keys',      Icon: KeysIcon },
  { id: 'config',     label: 'Routing Config',Icon: ConfigIcon },
  { id: 'settings',   label: 'Settings',      Icon: SettingsIcon },
]

const VALID_TABS = NAV.map(n => n.id)

function getTabFromPath() {
  if (typeof window === 'undefined') return 'landing'
  const path = window.location.pathname.replace(/^\/+|\/+$/g, '').toLowerCase()
  if (path === '' || path === 'landing') return 'landing'
  if (VALID_TABS.includes(path)) return path
  return 'landing'
}

// ponytail: static data from models.yaml — no API endpoint exists for this
const TIER_MODELS = {
  T1: [
    { model: 'gpt-5.4-nano',    provider: 'OpenAI', input: 0.20, output: 1.25,  ctx: '128K' },
    { model: 'gemini-flash-lite',provider: 'Google', input: 0.25, output: 1.50,  ctx: '1M'   },
    { model: 'llama-3.3-70b',   provider: 'Groq',   input: 0.59, output: 0.79,  ctx: '128K' },
  ],
  T2: [
    { model: 'gpt-5.4-mini',    provider: 'OpenAI', input: 0.75, output: 4.50,  ctx: '128K' },
    { model: 'gemini-flash',    provider: 'Google', input: 1.50, output: 9.00,  ctx: '1M'   },
    { model: 'groq-compound',   provider: 'Groq',   input: 0.59, output: 0.79,  ctx: '128K' },
  ],
  T3: [
    { model: 'gpt-5.4',         provider: 'OpenAI', input: 2.50, output: 15.00, ctx: '128K' },
    { model: 'gemini-pro',      provider: 'Google', input: 1.25, output: 10.00, ctx: '1M'   },
  ],
}

const TIER_DESC = {
  T1: 'Fast & cheap — simple queries, factual lookups',
  T2: 'Balanced — moderate complexity tasks',
  T3: 'Powerful — complex reasoning & long context',
}

function ModelDirectory() {
  return (
    <div className="flex-1 overflow-y-auto p-6">
      <div className="max-w-3xl mx-auto space-y-6">
        {Object.entries(TIER_MODELS).map(([tier, models]) => (
          <div key={tier} className="bg-zinc-50 rounded-2xl border border-zinc-200/80 overflow-hidden">
            <div className="px-5 py-3.5 border-b border-zinc-200/60 flex items-center gap-3">
              <span className="text-sm font-bold text-zinc-900">{tier}</span>
              <span className="text-xs text-zinc-500">{TIER_DESC[tier]}</span>
            </div>
            <div className="divide-y divide-zinc-100">
              {models.map(m => (
                <div key={m.model} className="flex items-center justify-between px-5 py-3 hover:bg-zinc-100/60 transition-colors">
                  <div>
                    <span className="text-sm font-mono font-medium text-zinc-900">{m.model}</span>
                    <span className="ml-2.5 text-xs text-zinc-400">{m.provider}</span>
                  </div>
                  <div className="flex items-center gap-6 text-xs font-mono text-zinc-500">
                    <span title="Input price per 1M tokens">${m.input} / 1M in</span>
                    <span title="Output price per 1M tokens">${m.output} / 1M out</span>
                    <span className="text-zinc-400">{m.ctx} ctx</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

function Placeholder({ page }) {
  return (
    <div className="flex-1 flex flex-col items-center justify-center text-zinc-400 p-8">
      <div className="w-12 h-12 rounded-full bg-zinc-100 flex items-center justify-center text-zinc-500 mb-3">
        <SettingsIcon />
      </div>
      <p className="text-sm font-medium text-zinc-600">{page}</p>
      <p className="text-xs text-zinc-400 mt-1">This section is currently in preview.</p>
    </div>
  )
}

// ─── What's New ─────────────────────────────────────────────────────────────

const WHATS_NEW_VERSION = '1.3.0'
const WHATS_NEW = [
  {
    tag: 'New',
    title: 'AI-powered Router v2',
    desc: 'A smarter classifier that uses AI to understand your prompt and pick the best model automatically.',
  },
  {
    tag: 'New',
    title: 'Refreshed interface',
    desc: 'Cleaner layout, smoother animations, and a more polished overall experience.',
  },
  {
    tag: 'Improved',
    title: 'Better routing for simple tasks',
    desc: 'Quick questions and simple requests now get routed faster and more efficiently.',
  },
  {
    tag: 'Improved',
    title: 'Smoother chat experience',
    desc: 'Responses stream more fluidly and the chat input stays responsive throughout your conversation.',
  },
]

const TAG_COLORS = {
  New: 'bg-violet-100 text-violet-700',
  Improved: 'bg-sky-100 text-sky-700',
  Fixed: 'bg-emerald-100 text-emerald-700',
}

function WhatsNewDropdown({ isOpen, onClose }) {
  const [shouldRender, setShouldRender] = useState(isOpen)
  const [isClosing, setIsClosing] = useState(false)

  useEffect(() => {
    if (isOpen) {
      setShouldRender(true)
      setIsClosing(false)
    } else if (shouldRender) {
      setIsClosing(true)
      const timer = setTimeout(() => {
        setShouldRender(false)
        setIsClosing(false)
      }, 150)
      return () => clearTimeout(timer)
    }
  }, [isOpen, shouldRender])

  if (!shouldRender) return null

  return (
    <div
      className={`absolute right-0 top-full mt-2 w-80 sm:w-96 bg-white rounded-2xl border border-zinc-200/90 shadow-xl z-50 overflow-hidden select-text ${
        isClosing ? 'animate-out' : 'animate-in'
      }`}
      onClick={e => e.stopPropagation()}
    >
      {/* Header */}
      <div className="px-4 py-3 border-b border-zinc-100 flex items-center justify-between bg-zinc-50/60">
        <div className="flex items-center gap-2">
          <h2 className="text-sm font-bold text-zinc-900">What's New</h2>
          <span className="text-[10px] font-semibold font-mono text-zinc-600 bg-zinc-100 px-2 py-0.5 rounded-full border border-zinc-200/80">
            v{WHATS_NEW_VERSION}
          </span>
        </div>
        <button
          onClick={onClose}
          className="w-6 h-6 rounded-full hover:bg-zinc-200/70 flex items-center justify-center text-zinc-400 hover:text-zinc-700 transition-colors"
          title="Đóng"
        >
          <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      {/* Items */}
      <div className="p-4 space-y-3 max-h-80 overflow-y-auto divide-y divide-zinc-100">
        {WHATS_NEW.map((item, i) => (
          <div key={i} className={`flex gap-3 ${i > 0 ? 'pt-3' : ''}`}>
            <div className="pt-0.5 flex-shrink-0">
              <span className={`inline-block px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wide ${TAG_COLORS[item.tag] || 'bg-zinc-100 text-zinc-600'}`}>
                {item.tag}
              </span>
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-xs font-semibold text-zinc-900">{item.title}</p>
              <p className="text-[11px] text-zinc-500 mt-0.5 leading-relaxed">{item.desc}</p>
            </div>
          </div>
        ))}
      </div>

      {/* Footer */}
      <div className="px-4 py-2.5 bg-zinc-50/70 border-t border-zinc-100 flex items-center justify-between">
        <span className="text-[11px] text-zinc-400 font-medium">SmartRoute Updates</span>
        <button
          onClick={onClose}
          className="text-xs font-semibold text-zinc-800 hover:text-zinc-950 px-2.5 py-1 rounded-md hover:bg-zinc-100 transition-colors"
        >
          Đã xem
        </button>
      </div>
    </div>
  )
}

// ─── Guided Tour ────────────────────────────────────────────────────────────

const TOUR_STEPS = [
  {
    target: '[data-tour="nav"]',
    title: 'Menu chính',
    desc: 'Chuyển đổi giữa Playground, Dashboard, Logs và các trang quản lý từ đây.',
    position: 'right',
  },
  {
    target: '[data-tour="sidebar"]',
    title: 'Lịch sử hội thoại',
    desc: 'Tất cả các cuộc trò chuyện gần đây được lưu ở đây. Nhấn vào để xem lại.',
    position: 'right',
  },
  {
    target: '[data-tour="input"]',
    title: 'Nhập câu hỏi',
    desc: 'Gõ bất kỳ câu hỏi nào — hệ thống sẽ tự động phân loại độ khó và chọn model phù hợp.',
    position: 'top',
  },
  {
    target: '[data-tour="classifier"]',
    title: 'Chọn bộ phân loại',
    desc: 'Heuristic dùng quy tắc nhanh, LLM dùng AI để phân loại chính xác hơn.',
    position: 'bottom',
  },
  {
    target: '[data-tour="policy"]',
    title: 'Chọn chính sách',
    desc: 'Balanced cân bằng chi phí & chất lượng. Quality ưu tiên model mạnh. Cost First tiết kiệm nhất.',
    position: 'bottom',
  },
]

function GuidedTour({ onFinish }) {
  const [step, setStep] = useState(0)
  const [rect, setRect] = useState(null)
  const tooltipRef = useRef(null)
  const [tooltipPos, setTooltipPos] = useState({ top: 0, left: 0 })

  useEffect(() => {
    function measure() {
      const targetSelector = TOUR_STEPS[step]?.target
      const el = targetSelector ? document.querySelector(targetSelector) : null
      if (el && (el.offsetWidth > 0 || el.offsetHeight > 0 || el.getClientRects().length > 0)) {
        el.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'nearest' })
        const r = el.getBoundingClientRect()
        setRect(r)
      } else {
        // Tự động bỏ qua bước này nếu element không hiển thị (ví dụ sidebar ẩn trên mobile)
        if (step < TOUR_STEPS.length - 1) {
          setStep(s => s + 1)
        } else {
          onFinish()
        }
      }
    }
    const t = setTimeout(measure, 120)
    window.addEventListener('resize', measure)
    return () => {
      clearTimeout(t)
      window.removeEventListener('resize', measure)
    }
  }, [step, onFinish])

  useLayoutEffect(() => {
    if (!rect) return
    const current = TOUR_STEPS[step]
    if (!current) return

    const pad = 8
    const margin = 16
    const vw = window.innerWidth
    const vh = window.innerHeight

    const tw = tooltipRef.current ? tooltipRef.current.offsetWidth : 288
    const th = tooltipRef.current ? tooltipRef.current.offsetHeight : 180

    let pos = current.position || 'bottom'

    // Tự động lật hướng nếu không đủ khoảng trống
    if (pos === 'right' && rect.right + pad + 12 + tw > vw - margin) {
      pos = (rect.bottom + pad + 12 + th <= vh - margin) ? 'bottom' : (rect.top - pad - 12 - th >= margin ? 'top' : 'bottom')
    } else if (pos === 'left' && rect.left - pad - 12 - tw < margin) {
      pos = (rect.bottom + pad + 12 + th <= vh - margin) ? 'bottom' : (rect.top - pad - 12 - th >= margin ? 'top' : 'bottom')
    } else if (pos === 'bottom' && rect.bottom + pad + 12 + th > vh - margin) {
      if (rect.top - pad - 12 - th >= margin) {
        pos = 'top'
      }
    } else if (pos === 'top' && rect.top - pad - 12 - th < margin) {
      if (rect.bottom + pad + 12 + th <= vh - margin) {
        pos = 'bottom'
      }
    }

    let top = 0
    let left = 0

    if (pos === 'right') {
      left = rect.right + pad + 12
      top = rect.top + rect.height / 2 - th / 2
    } else if (pos === 'left') {
      left = rect.left - pad - 12 - tw
      top = rect.top + rect.height / 2 - th / 2
    } else if (pos === 'top') {
      top = rect.top - pad - 12 - th
      left = rect.left + rect.width / 2 - tw / 2
    } else { // bottom
      top = rect.bottom + pad + 12
      left = rect.left + rect.width / 2 - tw / 2
    }

    // Đảm bảo tooltip nằm HOÀN TOÀN trong viewport (cách mép tối thiểu margin px)
    const clampedLeft = Math.max(margin, Math.min(vw - tw - margin, left))
    const clampedTop = Math.max(margin, Math.min(vh - th - margin, top))

    setTooltipPos({ top: clampedTop, left: clampedLeft })
  }, [rect, step])

  if (!rect) return null

  const current = TOUR_STEPS[step]
  const pad = 8
  const isLast = step === TOUR_STEPS.length - 1

  return (
    <div className="fixed inset-0 z-[60]">
      {/* Dark overlay with spotlight cutout */}
      <svg className="absolute inset-0 w-full h-full" style={{ pointerEvents: 'none' }}>
        <defs>
          <mask id="tour-mask">
            <rect width="100%" height="100%" fill="white" />
            <rect
              x={Math.max(0, rect.left - pad)} y={Math.max(0, rect.top - pad)}
              width={rect.width + pad * 2} height={rect.height + pad * 2}
              rx="12" fill="black"
            />
          </mask>
        </defs>
        <rect width="100%" height="100%" fill="rgba(0,0,0,0.45)" mask="url(#tour-mask)" />
      </svg>

      {/* Spotlight border ring */}
      <div
        className="absolute rounded-xl border-2 border-white/60 pointer-events-none transition-all duration-300"
        style={{
          top: Math.max(0, rect.top - pad),
          left: Math.max(0, rect.left - pad),
          width: rect.width + pad * 2,
          height: rect.height + pad * 2,
        }}
      />

      {/* Click blocker — must be before tooltip so tooltip stays on top */}
      <div className="absolute inset-0" onClick={onFinish} />

      {/* Tooltip */}
      <div
        ref={tooltipRef}
        className="absolute animate-in transition-all duration-200"
        style={{
          top: `${tooltipPos.top}px`,
          left: `${tooltipPos.left}px`,
          zIndex: 61,
        }}
      >
        <div className="bg-white rounded-2xl shadow-2xl p-5 w-72 max-w-[calc(100vw-32px)]">
          <div className="flex items-center justify-between mb-2">
            <h3 className="text-sm font-bold text-zinc-900">{current.title}</h3>
            <span className="text-[10px] font-mono text-zinc-400">{step + 1}/{TOUR_STEPS.length}</span>
          </div>
          <p className="text-xs text-zinc-500 leading-relaxed mb-4">{current.desc}</p>
          <div className="flex items-center justify-between">
            <button
              onClick={onFinish}
              className="text-xs text-zinc-400 hover:text-zinc-600 transition-colors cursor-pointer"
            >
              Bỏ qua
            </button>
            <button
              onClick={() => isLast ? onFinish() : setStep(s => s + 1)}
              className="px-4 py-1.5 rounded-full bg-zinc-900 text-white text-xs font-semibold hover:bg-zinc-800 transition-colors cursor-pointer"
            >
              {isLast ? 'Hoàn tất' : 'Tiếp theo'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

const MenuIcon = () => (
  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3.75 6.75h16.5M3.75 12h16.5m-16.5 5.25h16.5" />
  </svg>
)

const CloseIcon = () => (
  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
  </svg>
)

export default function App() {
  const [active, setActive] = useState(getTabFromPath)
  const [subTab, setSubTab] = useState(() => (getTabFromPath() === 'dashboard' ? 'metrics' : 'chat'))
  const [buildLabel, setBuildLabel] = useState(() => {
    const sha = import.meta.env.VITE_GIT_COMMIT_SHA
    return sha ? `sha-${sha.slice(0, 7)}` : null
  })
  const [sessionFeedbackOpen, setSessionFeedbackOpen] = useState(false)
  const [hasSession, setHasSession] = useState(false)
  const [showWhatsNew, setShowWhatsNew] = useState(false)
  const [hasUnreadWhatsNew, setHasUnreadWhatsNew] = useState(false)
  const [showTour, setShowTour] = useState(false)
  const [mobileNavOpen, setMobileNavOpen] = useState(false)
  const whatsNewRef = useRef(null)

  const navigateTo = (id) => {
    setActive(id)
    setSubTab(id === 'dashboard' ? 'metrics' : 'chat')
    const targetPath = id === 'landing' ? '/' : `/${id}`
    if (window.location.pathname !== targetPath) {
      window.history.pushState({ tab: id }, '', targetPath)
    }
  }

  const handleStartTour = () => {
    localStorage.removeItem('tour_done')
    navigateTo('playground')
    setShowTour(true)
  }

  useEffect(() => {
    window.restartTour = handleStartTour
    return () => {
      delete window.restartTour
    }
  }, [])

  useEffect(() => {
    const initialTab = getTabFromPath()
    const currentPath = window.location.pathname
    if (currentPath === '/' || currentPath === '' || currentPath === '/landing') {
      window.history.replaceState({ tab: 'landing' }, '', '/')
    } else if (VALID_TABS.includes(currentPath.replace(/^\/+|\/+$/g, '').toLowerCase())) {
      window.history.replaceState({ tab: initialTab }, '', `/${initialTab}`)
    } else {
      window.history.replaceState({ tab: 'landing' }, '', '/')
    }

    const handlePopState = () => {
      const tab = getTabFromPath()
      setActive(tab)
      setSubTab(tab === 'dashboard' ? 'metrics' : 'chat')
    }
    window.addEventListener('popstate', handlePopState)
    return () => window.removeEventListener('popstate', handlePopState)
  }, [])

  useEffect(() => {
    const seen = localStorage.getItem('whats_new_seen')
    if (seen !== WHATS_NEW_VERSION) {
      setHasUnreadWhatsNew(true)
    }
    if (!localStorage.getItem('tour_done')) {
      setShowTour(true)
    }
  }, [])

  useEffect(() => {
    if (buildLabel) return
    checkHealth().then(h => {
      if (h.commit_sha && h.commit_sha !== 'unknown') {
        setBuildLabel(`v${h.version} · ${h.commit_sha}`)
      }
    }).catch(() => {})
  }, [])

  useEffect(() => {
    function handleClickOutside(e) {
      if (whatsNewRef.current && !whatsNewRef.current.contains(e.target)) {
        setShowWhatsNew(false)
      }
    }
    if (showWhatsNew) {
      document.addEventListener('mousedown', handleClickOutside)
      return () => document.removeEventListener('mousedown', handleClickOutside)
    }
  }, [showWhatsNew])

  if (active === 'landing') {
    return <LandingPage onNavigate={navigateTo} />
  }

  const activeNavItem = NAV.find(n => n.id === active)
  const pageTitle = activeNavItem ? activeNavItem.label : 'Playground'

  const handleNavClick = (id) => {
    navigateTo(id)
    setMobileNavOpen(false)
  }

  return (
    <div className="flex h-screen bg-[#F5F6F8] font-sans antialiased text-zinc-900 overflow-hidden">
      {/* ─── Mobile Slide-over Navigation Drawer ───────────────────────── */}
      {mobileNavOpen && (
        <div className="fixed inset-0 z-50 md:hidden flex">
          <div
            className="fixed inset-0 bg-black/40 backdrop-blur-xs animate-fadeIn"
            onClick={() => setMobileNavOpen(false)}
          />
          <aside className="relative w-72 max-w-[85vw] bg-[#F5F6F8] flex flex-col justify-between p-3 select-none z-50 shadow-2xl animate-slide-in-left h-full border-r border-zinc-200">
            <div>
              <div className="flex items-center justify-between pr-2">
                <BrandLogo onClick={() => { navigateTo('landing'); setMobileNavOpen(false) }} />
                <button
                  onClick={() => setMobileNavOpen(false)}
                  className="w-8 h-8 rounded-full flex items-center justify-center text-zinc-500 hover:text-zinc-900 hover:bg-zinc-200/60 transition-colors"
                  aria-label="Đóng menu"
                >
                  <CloseIcon />
                </button>
              </div>
              <nav className="px-2 space-y-1 mt-3">
                {NAV.map(({ id, label, Icon }) => {
                  const isActive = active === id
                  return (
                    <button
                      key={id}
                      onClick={() => handleNavClick(id)}
                      className={`w-full flex items-center gap-3.5 px-3.5 py-3 rounded-xl text-sm font-medium transition-all ${
                        isActive
                          ? 'bg-zinc-200/80 text-zinc-900 font-semibold shadow-xs'
                          : 'text-zinc-600 hover:text-zinc-900 hover:bg-zinc-200/40'
                      }`}
                    >
                      <span className={isActive ? 'text-zinc-900' : 'text-zinc-400'}>
                        <Icon />
                      </span>
                      <span>{label}</span>
                    </button>
                  )
                })}
              </nav>
            </div>

            {/* Bottom Sidebar Status / Feedback in Mobile Drawer */}
            <div className="px-3 py-3 border-t border-zinc-200/70">
              {hasSession && (
                <button
                  onClick={() => {
                    setSessionFeedbackOpen(true)
                    setMobileNavOpen(false)
                  }}
                  className="w-full mb-3 flex items-center justify-center gap-2 px-3 py-2.5 rounded-full text-xs font-semibold text-zinc-800 bg-white border border-zinc-200/80 hover:bg-zinc-50 transition-colors shadow-xs"
                >
                  <span>✨ Phản hồi phiên</span>
                </button>
              )}
              <div className="flex items-center justify-between px-2 py-1 text-[11px] text-zinc-500">
                <span className="flex items-center gap-2">
                  <span className="w-2 h-2 rounded-full bg-emerald-500" />
                  <span>Gateway Live</span>
                </span>
                <span>{buildLabel || 'v1.2'}</span>
              </div>
            </div>
          </aside>
        </div>
      )}

      {/* ─── Desktop Left Sidebar ────────────────────────────────────────── */}
      <aside className="hidden md:flex w-60 flex-none bg-[#F5F6F8] flex-col justify-between py-2 select-none">
        <div>
          <BrandLogo onClick={() => navigateTo('landing')} />
          <nav data-tour="nav" className="px-3 space-y-1 mt-2">
            {NAV.map(({ id, label, Icon }) => {
              const isActive = active === id
              return (
                <button
                  key={id}
                  onClick={() => navigateTo(id)}
                  className={`w-full flex items-center gap-3.5 px-3.5 py-2.5 rounded-xl text-sm font-medium transition-all ${
                    isActive
                      ? 'bg-zinc-200/70 text-zinc-900 font-semibold shadow-xs'
                      : 'text-zinc-500 hover:text-zinc-900 hover:bg-zinc-200/40'
                  }`}
                >
                  <span className={isActive ? 'text-zinc-900' : 'text-zinc-400'}>
                    <Icon />
                  </span>
                  <span>{label}</span>
                </button>
              )
            })}
          </nav>
        </div>

        {/* Bottom Sidebar Status / Feedback */}
        <div className="px-4 py-3">
          {hasSession && (
            <button
              onClick={() => setSessionFeedbackOpen(true)}
              className="w-full mb-3 flex items-center justify-center gap-2 px-3 py-2 rounded-full text-xs font-semibold text-zinc-800 bg-white border border-zinc-200/80 hover:bg-zinc-50 transition-colors shadow-xs"
            >
              <span>✨ Phản hồi phiên</span>
            </button>
          )}
          <div className="flex items-center gap-2 px-2 py-1 text-[11px] text-zinc-400">
            <span className="w-2 h-2 rounded-full bg-emerald-500" />
            <span>{buildLabel || 'v1.2'}</span>
          </div>
        </div>
      </aside>

      {/* ─── Main Content Canvas & Header ─────────────────────────────── */}
      <div className="flex-1 flex flex-col min-w-0 p-2 sm:p-3 md:pr-6 md:pb-6 md:pt-3 h-full overflow-hidden">
        {/* Top Header Bar */}
        <header className="flex flex-col sm:flex-row sm:items-center justify-between px-2 py-2 sm:py-3 mb-1 sm:mb-2 flex-none gap-2">
          <div className="flex items-center justify-between sm:justify-start gap-3 sm:gap-6">
            <div className="flex items-center gap-2">
              {/* Mobile Hamburger Button */}
              <button
                type="button"
                onClick={() => setMobileNavOpen(true)}
                className="md:hidden p-2 -ml-1 text-zinc-600 hover:text-zinc-900 hover:bg-zinc-200/60 rounded-xl transition-colors"
                aria-label="Mở menu"
              >
                <MenuIcon />
              </button>
              <h1 className="text-xl sm:text-2xl font-bold tracking-tight text-zinc-900 truncate">
                {pageTitle}
              </h1>
            </div>

            {/* Mobile-friendly Subtabs */}
            {active === 'playground' && (
              <div className="hidden sm:flex items-center gap-1.5 text-xs font-medium text-zinc-500 overflow-x-auto no-scrollbar">
                <button
                  onClick={() => setSubTab('chat')}
                  className={`px-3 py-1.5 rounded-full transition-colors whitespace-nowrap ${
                    subTab === 'chat'
                      ? 'bg-zinc-200/80 text-zinc-900 font-semibold'
                      : 'hover:text-zinc-900'
                  }`}
                >
                  Interactive Chat
                </button>
                <button
                  onClick={() => setSubTab('insights')}
                  className={`px-3 py-1.5 rounded-full transition-colors whitespace-nowrap ${
                    subTab === 'insights'
                      ? 'bg-zinc-200/80 text-zinc-900 font-semibold'
                      : 'hover:text-zinc-900'
                  }`}
                >
                  Routing Insights
                </button>
                <button
                  onClick={() => setSubTab('models')}
                  className={`px-3 py-1.5 rounded-full transition-colors whitespace-nowrap ${
                    subTab === 'models'
                      ? 'bg-zinc-200/80 text-zinc-900 font-semibold'
                      : 'hover:text-zinc-900'
                  }`}
                >
                  Model Directory
                </button>
              </div>
            )}
            {active === 'dashboard' && (
              <div className="hidden sm:flex items-center gap-1.5 text-xs font-medium text-zinc-500 overflow-x-auto no-scrollbar">
                <button
                  onClick={() => setSubTab('metrics')}
                  className={`px-3 py-1.5 rounded-full transition-colors whitespace-nowrap ${
                    subTab === 'metrics'
                      ? 'bg-zinc-200/80 text-zinc-900 font-semibold'
                      : 'hover:text-zinc-900'
                  }`}
                >
                  Overview &amp; KPIs
                </button>
                <button
                  onClick={() => setSubTab('breakdown')}
                  className={`px-3 py-1.5 rounded-full transition-colors whitespace-nowrap ${
                    subTab === 'breakdown'
                      ? 'bg-zinc-200/80 text-zinc-900 font-semibold'
                      : 'hover:text-zinc-900'
                  }`}
                >
                  Tier &amp; Provider
                </button>
              </div>
            )}

            {/* Mobile actions in top bar */}
            <div className="flex items-center gap-1.5 sm:hidden">
              <div ref={whatsNewRef} className="relative">
                <button
                  type="button"
                  onClick={() => {
                    setShowWhatsNew(prev => {
                      const next = !prev
                      if (next && hasUnreadWhatsNew) {
                        setHasUnreadWhatsNew(false)
                        localStorage.setItem('whats_new_seen', WHATS_NEW_VERSION)
                      }
                      return next
                    })
                  }}
                  title="What's New"
                  className={`w-7 h-7 rounded-full border border-zinc-200 flex items-center justify-center transition-colors relative shadow-2xs ${
                    showWhatsNew ? 'bg-zinc-100 text-zinc-900' : 'bg-white text-zinc-600'
                  }`}
                >
                  <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" />
                  </svg>
                  {hasUnreadWhatsNew && (
                    <span className="absolute top-0.5 right-0.5 w-2 h-2 bg-emerald-500 rounded-full ring-1 ring-white" />
                  )}
                </button>

                <WhatsNewDropdown
                  isOpen={showWhatsNew}
                  onClose={() => {
                    setShowWhatsNew(false)
                    setHasUnreadWhatsNew(false)
                    localStorage.setItem('whats_new_seen', WHATS_NEW_VERSION)
                  }}
                />
              </div>

              <button
                onClick={() => navigateTo('keys')}
                className="w-7 h-7 rounded-full bg-white border border-zinc-300 text-zinc-800 text-[10px] font-bold flex items-center justify-center shadow-2xs"
                title="API Keys"
              >
                +Key
              </button>
            </div>
          </div>

          {/* Desktop Top Right Actions */}
          <div className="hidden sm:flex items-center gap-2.5">
            {/* Status Online Pill */}
            <div className="flex items-center gap-2 bg-zinc-900 text-white text-xs font-semibold px-3.5 py-1.5 rounded-full shadow-xs select-none">
              <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
              <span>Gateway Live</span>
            </div>

            {/* White Pill Button */}
            <button
              onClick={() => navigateTo('keys')}
              className="flex items-center gap-1.5 bg-white border border-zinc-300/90 hover:bg-zinc-50 text-zinc-800 text-xs font-bold tracking-wider px-3.5 py-1.5 rounded-full transition-colors shadow-xs uppercase"
            >
              <span>+ API KEY</span>
            </button>

            {/* Help Question Icon */}
            <button
              onClick={handleStartTour}
              title="Tour Guide"
              className="w-8 h-8 rounded-full border border-zinc-200 bg-white flex items-center justify-center text-zinc-600 hover:text-zinc-900 hover:bg-zinc-50 transition-colors shadow-xs text-xs font-bold cursor-pointer"
            >
              ?
            </button>

            {/* Notification Bell Icon & Dropdown */}
            <div ref={whatsNewRef} className="relative">
              <button
                type="button"
                onClick={() => {
                  setShowWhatsNew(prev => {
                    const next = !prev
                    if (next && hasUnreadWhatsNew) {
                      setHasUnreadWhatsNew(false)
                      localStorage.setItem('whats_new_seen', WHATS_NEW_VERSION)
                    }
                    return next
                  })
                }}
                title="What's New"
                className={`w-8 h-8 rounded-full border border-zinc-200 flex items-center justify-center transition-colors relative shadow-xs cursor-pointer ${
                  showWhatsNew ? 'bg-zinc-100 text-zinc-900 border-zinc-300' : 'bg-white text-zinc-600 hover:text-zinc-900 hover:bg-zinc-50'
                }`}
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" />
                </svg>
                {hasUnreadWhatsNew && (
                  <span className="absolute top-1.5 right-1.5 w-2 h-2 bg-emerald-500 rounded-full ring-2 ring-white" />
                )}
              </button>

              <WhatsNewDropdown
                isOpen={showWhatsNew}
                onClose={() => {
                  setShowWhatsNew(false)
                  setHasUnreadWhatsNew(false)
                  localStorage.setItem('whats_new_seen', WHATS_NEW_VERSION)
                }}
              />
            </div>

            {/* User Initials Avatar */}
            <div className="w-8 h-8 rounded-full bg-zinc-200 border border-zinc-300 flex items-center justify-center text-xs font-bold text-zinc-800 select-none">
              SR
            </div>
          </div>
        </header>

        {/* ─── Floating Main App Card (Origin Style Canvas) ───────────── */}
        <main className="flex-1 bg-white rounded-2xl sm:rounded-3xl md:rounded-[28px] border border-zinc-200/80 shadow-sm overflow-hidden flex flex-col min-h-0">
          {active === 'playground' && subTab === 'insights' ? (
            <StatsPage />
          ) : active === 'playground' && subTab === 'models' ? (
            <ModelDirectory />
          ) : active === 'playground' ? (
            <Playground
              sessionFeedbackOpen={sessionFeedbackOpen}
              onSessionFeedbackClose={() => setSessionFeedbackOpen(false)}
              onSessionStart={() => setHasSession(true)}
            />
          ) : active === 'dashboard' ? (
            <StatsPage />
          ) : active === 'logs' ? (
            <RequestLogs />
          ) : active === 'config' ? (
            <ConfigPanel />
          ) : active === 'keys' ? (
            <ApiKeys />
          ) : (
            <Placeholder page={activeNavItem?.label} />
          )}
        </main>
      </div>

      {showTour && (
        <GuidedTour onFinish={() => {
          setShowTour(false)
          localStorage.setItem('tour_done', '1')
        }} />
      )}
    </div>
  )
}

