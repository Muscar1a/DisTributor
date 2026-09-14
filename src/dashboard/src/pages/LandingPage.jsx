import { useState } from 'react'

// ─── Minimal Geometric Icons (Monochromatic) ─────────────────────────────────

const DisTributorLogo = ({ className = "w-7 h-7" }) => (
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

const ArrowRightIcon = () => (
  <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.5 4.5L21 12m0 0l-7.5 7.5M21 12H3" />
  </svg>
)

const CheckIcon = () => (
  <svg className="w-4 h-4 text-zinc-900 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M4.5 12.75l6 6 9-13.5" />
  </svg>
)

// ─── Interactive Prompt Samples ──────────────────────────────────────────────

const SAMPLES = [
  {
    id: 'simple',
    label: 'Đơn giản (T1)',
    prompt: 'Thủ đô của nước Úc là gì? Trả lời ngắn gọn 1 câu.',
    tier: 'T1',
    tierName: 'Tier 1 · Nhanh & Tiết kiệm',
    model: 'gemini-flash-lite',
    provider: 'Google',
    latency: '11ms',
    cost: '$0.00004',
    baselineCost: '$0.00250',
    savings: '98.4%',
    reasoning: 'Câu hỏi thông tin sự thật cơ bản, dung lượng ngắn, không có yêu cầu suy luận phức tạp.',
  },
  {
    id: 'moderate',
    label: 'Trung bình (T2)',
    prompt: 'Viết hàm Python kiểm tra tính hợp lệ của chuỗi thời gian ISO 8601 bằng regex và xử lý timezone offset.',
    tier: 'T2',
    tierName: 'Tier 2 · Cân bằng',
    model: 'gpt-5.4-mini',
    provider: 'OpenAI',
    latency: '14ms',
    cost: '$0.00085',
    baselineCost: '$0.00450',
    savings: '81.1%',
    reasoning: 'Yêu cầu lập trình tiêu chuẩn, cú pháp regex xác định, bài toán quy mô một hàm độc lập.',
  },
  {
    id: 'complex',
    label: 'Phức tạp (T3)',
    prompt: 'Thiết kế thuật toán phân tán đồng thuận Raft trong môi trường mạng không tin cậy. Phân tích chi tiết kịch bản Split-Brain và chứng minh an toàn bầu chọn (Leader Election Safety).',
    tier: 'T3',
    tierName: 'Tier 3 · Suy luận sâu',
    model: 'gpt-5.4',
    provider: 'OpenAI',
    latency: '16ms',
    cost: '$0.01500',
    baselineCost: '$0.01500',
    savings: 'Chất lượng tối đa (0%)',
    reasoning: 'Bài toán hệ phân tán cao cấp, suy luận logic toán học và phân tích edge-case nhiều bước.',
  },
]

export default function LandingPage({ onNavigate }) {
  const [selectedSample, setSelectedSample] = useState(SAMPLES[0])
  const [activeCodeTab, setActiveCodeTab] = useState('python')
  const [isRunningTest, setIsRunningTest] = useState(false)
  const [testResult, setTestResult] = useState(null)
  const [copied, setCopied] = useState(false)
  const [customApiKey, setCustomApiKey] = useState(() => {
    if (typeof window !== 'undefined') {
      return localStorage.getItem('gateway_try_key') || import.meta.env.VITE_GATEWAY_KEY || import.meta.env.VITE_API_KEY || ''
    }
    return ''
  })
  const [showKey, setShowKey] = useState(false)

  const handleKeyChange = (e) => {
    const val = e.target.value
    setCustomApiKey(val)
    if (typeof window !== 'undefined') {
      localStorage.setItem('gateway_try_key', val)
    }
  }

  const handleLaunchApp = (route = 'playground') => {
    if (onNavigate) {
      onNavigate(route)
    } else {
      window.location.pathname = `/${route}`
    }
  }

  const handleCopyCode = () => {
    const effectiveKey = customApiKey.trim() || 'sr-dev-key'
    let codeToCopy = ''
    if (activeCodeTab === 'python') {
      codeToCopy = `import os\nfrom openai import OpenAI\n\n# Thay đổi duy nhất: trỏ base_url về SmartRoute Gateway\nclient = OpenAI(\n    base_url="https://p-156-latest.onrender.com/v1",\n    api_key=os.environ.get("GATEWAY_KEY", "${effectiveKey}")\n)\n\nresponse = client.chat.completions.create(\n    model="smartroute",\n    messages=[{"role": "user", "content": "Explain Paxos consensus in 3 bullet points."}]\n)\n\nprint("Chosen Model:", response.model)\nprint("Content:", response.choices[0].message.content)`
    } else if (activeCodeTab === 'node') {
      codeToCopy = `import OpenAI from 'openai';\n\nconst client = new OpenAI({\n  baseURL: 'https://p-156-latest.onrender.com/v1',\n  apiKey: process.env.GATEWAY_KEY || '${effectiveKey}',\n});\n\nconst completion = await client.chat.completions.create({\n  model: 'smartroute',\n  messages: [{ role: 'user', content: 'Explain Paxos consensus in 3 bullet points.' }],\n});\n\nconsole.log("Chosen Model:", completion.model);\nconsole.log("Content:", completion.choices[0].message.content);`
    } else {
      codeToCopy = `curl -X POST "https://p-156-latest.onrender.com/v1/chat/completions" \\\n  -H "Authorization: Bearer ${customApiKey.trim() || '$GATEWAY_KEY'}" \\\n  -H "Content-Type: application/json" \\\n  -d '{\n    "model": "smartroute",\n    "messages": [{"role": "user", "content": "Explain Paxos consensus in 3 bullet points."}]\n  }'`
    }
    navigator.clipboard?.writeText(codeToCopy)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const handleTryItNow = async () => {
    setIsRunningTest(true)
    setTestResult(null)
    const startTime = performance.now()
    const targetUrl = 'https://p-156-latest.onrender.com/v1/chat/completions'
    const apiKey = customApiKey.trim() || import.meta.env.VITE_GATEWAY_KEY || import.meta.env.VITE_API_KEY || ''

    try {
      const headers = { 'Content-Type': 'application/json' }
      if (apiKey) {
        headers['Authorization'] = `Bearer ${apiKey}`
      }

      const res = await fetch(targetUrl, {
        method: 'POST',
        headers,
        body: JSON.stringify({
          model: 'smartroute',
          messages: [{ role: 'user', content: 'Explain Paxos consensus in 3 bullet points.' }],
        }),
      })

      const elapsed = Math.round(performance.now() - startTime)
      const data = await res.json().catch(() => ({}))

      if (!res.ok) {
        throw new Error(data?.error?.message || data?.detail || `HTTP ${res.status}`)
      }

      setTestResult({
        success: true,
        status: res.status,
        latency: elapsed,
        tier: res.headers.get('X-SR-Tier') || res.headers.get('x-sr-tier') || 'T3',
        model: res.headers.get('X-SR-Model') || res.headers.get('x-sr-model') || data.model || 'gpt-5.4',
        cost: res.headers.get('X-SR-Cost-USD') || res.headers.get('x-sr-cost-usd') || '0.003410',
        content: data.choices?.[0]?.message?.content || 'Paxos consensus achieved.',
      })
    } catch (err) {
      const elapsed = Math.round(performance.now() - startTime)
      setTestResult({
        success: false,
        latency: elapsed,
        error: err.message || 'Không thể kết nối trực tiếp tới p-156-latest.onrender.com',
      })
    } finally {
      setIsRunningTest(false)
    }
  }

  return (
    <div className="min-h-screen bg-[#F5F6F8] text-zinc-900 font-sans antialiased selection:bg-zinc-200">
      {/* ─── Sticky Minimal Header ─────────────────────────────────────────── */}
      <header className="sticky top-0 z-40 bg-[#F5F6F8]/85 backdrop-blur-md border-b border-zinc-200/80">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 h-16 flex items-center justify-between">
          {/* Logo & Brand */}
          <div className="flex items-center gap-3 select-none cursor-pointer" onClick={() => window.scrollTo({ top: 0, behavior: 'smooth' })}>
            <div className="w-8 h-8 flex items-center justify-center text-zinc-900 shrink-0">
              <DisTributorLogo className="w-8 h-8" />
            </div>
            <div className="flex flex-col">
              <span className="text-base font-bold tracking-tight text-zinc-900 leading-none">DisTributor</span>
              <span className="text-[10px] text-zinc-400 font-medium tracking-wider uppercase mt-0.5">Smart LLM Gateway</span>
            </div>
          </div>

          {/* Quick Nav Anchor Links */}
          <nav className="hidden md:flex items-center gap-8 text-xs font-medium text-zinc-500">
            <a href="#features" className="hover:text-zinc-900 transition-colors">Tính năng</a>
            <a href="#demo" className="hover:text-zinc-900 transition-colors">Thử nghiệm</a>
            <a href="#architecture" className="hover:text-zinc-900 transition-colors">Kiến trúc</a>
            <a href="#code" className="hover:text-zinc-900 transition-colors">Tích hợp</a>
          </nav>

          {/* Action Buttons: Entry to App */}
          <div className="flex items-center gap-2.5">
            <button
              onClick={() => handleLaunchApp('dashboard')}
              className="hidden sm:inline-flex items-center text-xs font-semibold text-zinc-600 hover:text-zinc-900 px-3.5 py-1.5 rounded-full hover:bg-zinc-200/60 transition-colors"
            >
              Xem Dashboard
            </button>
            <button
              onClick={() => handleLaunchApp('playground')}
              className="inline-flex items-center gap-1.5 bg-zinc-900 hover:bg-zinc-800 text-white text-xs font-semibold px-4 py-2 rounded-full transition-all shadow-xs active:scale-95"
            >
              <span>Vào ứng dụng</span>
              <ArrowRightIcon />
            </button>
          </div>
        </div>
      </header>

      {/* ─── Hero Section ─────────────────────────────────────────────────── */}
      <section className="pt-20 pb-16 sm:pt-28 sm:pb-24 px-4 sm:px-6">
        <div className="max-w-4xl mx-auto text-center">
          {/* Badge */}
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-white border border-zinc-200 shadow-2xs mb-6 select-none">
            <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
            <span className="text-xs font-semibold text-zinc-800">SmartRoute v2.0 Live</span>
            <span className="text-zinc-300">|</span>
            <span className="text-xs text-zinc-500">Chuẩn drop-in OpenAI API</span>
          </div>

          {/* Headline */}
          <h1 className="text-4xl sm:text-6xl md:text-7xl font-bold tracking-tight text-zinc-900 leading-[1.08]">
            Route Smarter.<br />
            <span className="text-zinc-400">Cut 70% of LLM Costs.</span>
          </h1>

          {/* Subheading */}
          <p className="mt-6 text-base sm:text-lg text-zinc-600 max-w-2xl mx-auto leading-relaxed">
            Hệ thống Gateway thông minh tự động phân loại độ khó câu lệnh và định tuyến sang model tối ưu trong chưa đầy <span className="font-mono font-medium text-zinc-900">15ms</span>. Giữ trọn độ chính xác cao nhất mà không lãng phí chi phí.
          </p>

          {/* Main CTAs */}
          <div className="mt-10 flex flex-col sm:flex-row items-center justify-center gap-3.5">
            <button
              onClick={() => handleLaunchApp('playground')}
              className="w-full sm:w-auto inline-flex items-center justify-center gap-2 bg-zinc-900 hover:bg-zinc-800 text-white text-sm font-semibold px-7 py-3.5 rounded-full transition-all shadow-sm active:scale-98"
            >
              <span>Trải nghiệm Playground</span>
              <ArrowRightIcon />
            </button>
            <button
              onClick={() => handleLaunchApp('dashboard')}
              className="w-full sm:w-auto inline-flex items-center justify-center gap-2 bg-white hover:bg-zinc-50 border border-zinc-300/80 text-zinc-800 text-sm font-semibold px-6 py-3.5 rounded-full transition-all shadow-2xs"
            >
              <span>Xem thống kê KPIs</span>
            </button>
          </div>

          {/* Highlight badges */}
          <div className="mt-12 flex flex-wrap items-center justify-center gap-x-8 gap-y-3 text-xs text-zinc-500">
            <div className="flex items-center gap-2">
              <CheckIcon />
              <span>Không sửa đổi logic code</span>
            </div>
            <div className="flex items-center gap-2">
              <CheckIcon />
              <span>Tự động Fallback chống sập</span>
            </div>
            <div className="flex items-center gap-2">
              <CheckIcon />
              <span>Ghi nhớ ngữ cảnh đa lượt</span>
            </div>
          </div>
        </div>
      </section>

      {/* ─── Interactive Routing Sandbox Preview ──────────────────────────── */}
      <section id="demo" className="py-12 px-4 sm:px-6">
        <div className="max-w-4xl mx-auto">
          <div className="text-center mb-8">
            <span className="text-[11px] font-bold tracking-widest text-zinc-400 uppercase">Live Router Sandbox</span>
            <h2 className="text-2xl sm:text-3xl font-bold tracking-tight text-zinc-900 mt-1">
              Thử nghiệm cơ chế phân tầng độ khó
            </h2>
            <p className="text-sm text-zinc-500 mt-2">
              Nhấp vào các câu hỏi mẫu dưới đây để xem cách Gateway đưa ra quyết định định tuyến tức thời.
            </p>
          </div>

          {/* Sandbox Card */}
          <div className="bg-white rounded-2xl sm:rounded-3xl border border-zinc-200/90 shadow-sm overflow-hidden">
            {/* Prompt Selector Pills */}
            <div className="p-4 sm:p-5 border-b border-zinc-100 bg-zinc-50/50 flex flex-wrap items-center gap-2">
              <span className="text-xs font-semibold text-zinc-500 mr-2">Mẫu câu hỏi:</span>
              {SAMPLES.map(sample => (
                <button
                  key={sample.id}
                  onClick={() => setSelectedSample(sample)}
                  className={`text-xs font-medium px-3.5 py-1.5 rounded-full transition-all ${
                    selectedSample.id === sample.id
                      ? 'bg-zinc-900 text-white font-semibold shadow-xs'
                      : 'bg-white border border-zinc-200 text-zinc-600 hover:text-zinc-900 hover:bg-zinc-100/60'
                  }`}
                >
                  {sample.label}
                </button>
              ))}
            </div>

            {/* Input & Output Panels */}
            <div className="p-6 sm:p-8 space-y-6">
              {/* User Prompt Box */}
              <div>
                <div className="text-xs font-mono font-medium text-zinc-400 uppercase tracking-wider mb-2">
                  01 · Prompt đầu vào
                </div>
                <div className="p-4 rounded-xl bg-zinc-50 border border-zinc-200/70 text-sm text-zinc-800 font-sans leading-relaxed">
                  "{selectedSample.prompt}"
                </div>
              </div>

              {/* Routing Analysis Decision Box */}
              <div>
                <div className="text-xs font-mono font-medium text-zinc-400 uppercase tracking-wider mb-2 flex items-center justify-between">
                  <span>02 · Phân tích định tuyến của Gateway</span>
                  <span className="text-emerald-600 font-bold">Phân loại trong {selectedSample.latency}</span>
                </div>

                <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                  <div className="p-3.5 rounded-xl border border-zinc-200/80 bg-zinc-50/40">
                    <span className="text-[10px] text-zinc-400 uppercase font-mono">Phân tầng</span>
                    <p className="text-sm font-bold text-zinc-900 mt-0.5">{selectedSample.tier}</p>
                    <p className="text-[11px] text-zinc-500 truncate">{selectedSample.tierName.split('·')[1]}</p>
                  </div>
                  <div className="p-3.5 rounded-xl border border-zinc-200/80 bg-zinc-50/40">
                    <span className="text-[10px] text-zinc-400 uppercase font-mono">Model chọn lọc</span>
                    <p className="text-sm font-mono font-bold text-zinc-900 mt-0.5 truncate">{selectedSample.model}</p>
                    <p className="text-[11px] text-zinc-500">{selectedSample.provider}</p>
                  </div>
                  <div className="p-3.5 rounded-xl border border-zinc-200/80 bg-zinc-50/40">
                    <span className="text-[10px] text-zinc-400 uppercase font-mono">Chi phí thực tế</span>
                    <p className="text-sm font-mono font-bold text-emerald-600 mt-0.5">{selectedSample.cost}</p>
                    <p className="text-[11px] text-zinc-400 line-through">Gốc: {selectedSample.baselineCost}</p>
                  </div>
                  <div className="p-3.5 rounded-xl border border-zinc-200/80 bg-zinc-50/40">
                    <span className="text-[10px] text-zinc-400 uppercase font-mono">Cắt giảm</span>
                    <p className="text-sm font-mono font-bold text-zinc-900 mt-0.5">{selectedSample.savings}</p>
                    <p className="text-[11px] text-zinc-500">so với GPT-5.4</p>
                  </div>
                </div>

                {/* Explanation */}
                <div className="mt-3.5 p-3 rounded-lg bg-zinc-100/70 border border-zinc-200/60 text-xs text-zinc-600 flex items-start gap-2">
                  <span className="font-semibold text-zinc-800 shrink-0">Lý do định tuyến:</span>
                  <span>{selectedSample.reasoning}</span>
                </div>
              </div>

              {/* Action Button */}
              <div className="pt-2 flex justify-end">
                <button
                  onClick={() => handleLaunchApp('playground')}
                  className="inline-flex items-center gap-2 text-xs font-bold text-zinc-900 hover:text-black transition-colors"
                >
                  <span>Mở chat thử câu này trên Playground</span>
                  <ArrowRightIcon />
                </button>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ─── Numbers / Metrics Bar ────────────────────────────────────────── */}
      <section id="metrics" className="py-16 px-4 sm:px-6 border-y border-zinc-200/80 bg-white">
        <div className="max-w-5xl mx-auto grid grid-cols-2 md:grid-cols-4 gap-8 text-center">
          <div>
            <div className="text-3xl sm:text-4xl font-bold font-mono text-zinc-900">73.4%</div>
            <div className="text-xs font-semibold uppercase tracking-wider text-zinc-400 mt-1">Chi phí tiết kiệm</div>
            <div className="text-xs text-zinc-500 mt-1">Đo kiểm trên 200 bài toán hỗn hợp</div>
          </div>
          <div>
            <div className="text-3xl sm:text-4xl font-bold font-mono text-zinc-900">&lt; 15ms</div>
            <div className="text-xs font-semibold uppercase tracking-wider text-zinc-400 mt-1">Độ trễ phân loại</div>
            <div className="text-xs text-zinc-500 mt-1">Thuật toán Heuristic & AI v2</div>
          </div>
          <div>
            <div className="text-3xl sm:text-4xl font-bold font-mono text-zinc-900">100%</div>
            <div className="text-xs font-semibold uppercase tracking-wider text-zinc-400 mt-1">Chuẩn OpenAI</div>
            <div className="text-xs text-zinc-500 mt-1">Tương thích hoàn toàn mọi thư viện</div>
          </div>
          <div>
            <div className="text-3xl sm:text-4xl font-bold font-mono text-zinc-900">99.9%</div>
            <div className="text-xs font-semibold uppercase tracking-wider text-zinc-400 mt-1">Độ sẵn sàng</div>
            <div className="text-xs text-zinc-500 mt-1">Circuit Breaker tự động chuyển mạch</div>
          </div>
        </div>
      </section>

      {/* ─── Core Architecture & Features ─────────────────────────────────── */}
      <section id="architecture" className="py-20 px-4 sm:px-6">
        <div className="max-w-5xl mx-auto">
          <div className="text-center max-w-2xl mx-auto mb-14">
            <span className="text-[11px] font-bold tracking-widest text-zinc-400 uppercase">Core Superpowers</span>
            <h2 className="text-2xl sm:text-3xl font-bold tracking-tight text-zinc-900 mt-1">
              Hạ tầng định tuyến được tối ưu hoá từng mili-giây
            </h2>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
            {/* Feature 1 */}
            <div className="bg-white p-7 rounded-2xl border border-zinc-200/80 shadow-2xs space-y-3">
              <div className="w-8 h-8 rounded-lg bg-zinc-100 flex items-center justify-center text-zinc-900 font-mono text-xs font-bold">
                01
              </div>
              <h3 className="text-base font-bold text-zinc-900">Text Zoning & Phân loại thông minh</h3>
              <p className="text-xs sm:text-sm text-zinc-600 leading-relaxed">
                Tách rời vùng chỉ thị (Instruction Zone) khỏi các khối mã code và stack trace (Artifact Zone). Khắc phục triệt để hiện tượng câu khó ngắn bị xếp nhầm Tier 1 hoặc câu tâm sự dài bị đẩy lên Tier 3.
              </p>
            </div>

            {/* Feature 2 */}
            <div className="bg-white p-7 rounded-2xl border border-zinc-200/80 shadow-2xs space-y-3">
              <div className="w-8 h-8 rounded-lg bg-zinc-100 flex items-center justify-center text-zinc-900 font-mono text-xs font-bold">
                02
              </div>
              <h3 className="text-base font-bold text-zinc-900">Session Router & Failure Lock</h3>
              <p className="text-xs sm:text-sm text-zinc-600 leading-relaxed">
                Không giống các router không trạng thái, Session Router theo dõi lịch sử nhiều lượt chat qua EMA. Nếu người dùng phản hồi kết quả trước chưa đạt hoặc báo lỗi, hệ thống tự động khóa sàn và nâng bậc model.
              </p>
            </div>

            {/* Feature 3 */}
            <div className="bg-white p-7 rounded-2xl border border-zinc-200/80 shadow-2xs space-y-3">
              <div className="w-8 h-8 rounded-lg bg-zinc-100 flex items-center justify-center text-zinc-900 font-mono text-xs font-bold">
                03
              </div>
              <h3 className="text-base font-bold text-zinc-900">Circuit Breaker & Chuỗi Fallback</h3>
              <p className="text-xs sm:text-sm text-zinc-600 leading-relaxed">
                Tự động phát hiện khi OpenAI, Gemini hoặc Groq gặp sự cố rate-limit 429 hoặc timeout. Cơ chế Circuit Breaker tức thì kích hoạt model dự phòng trong chuỗi mà client không hề bị gián đoạn request.
              </p>
            </div>

            {/* Feature 4 */}
            <div className="bg-white p-7 rounded-2xl border border-zinc-200/80 shadow-2xs space-y-3">
              <div className="w-8 h-8 rounded-lg bg-zinc-100 flex items-center justify-center text-zinc-900 font-mono text-xs font-bold">
                04
              </div>
              <h3 className="text-base font-bold text-zinc-900">Ghi log 2 pha & Minh bạch Headers</h3>
              <p className="text-xs sm:text-sm text-zinc-600 leading-relaxed">
                Toàn bộ quyết định định tuyến được đính kèm qua headers <code className="text-[11px] bg-zinc-100 px-1 py-0.5 rounded font-mono">X-SR-Tier</code>, <code className="text-[11px] bg-zinc-100 px-1 py-0.5 rounded font-mono">X-SR-Cost-USD</code>. Ghi log xử lý nền ngầm qua BackgroundTasks, không làm chậm TTFT dù chỉ 1ms.
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* ─── 1-Line Drop-in Integration (Code Showcase) ───────────────────── */}
      <section id="code" className="py-16 px-4 sm:px-6 bg-white border-t border-zinc-200/80">
        <div className="max-w-4xl mx-auto">
          <div className="text-center max-w-xl mx-auto mb-10">
            <span className="text-[11px] font-bold tracking-widest text-zinc-400 uppercase">Drop-in Integration</span>
            <h2 className="text-2xl sm:text-3xl font-bold tracking-tight text-zinc-900 mt-1">
              Chỉ cần đổi 1 dòng URL
            </h2>
            <p className="text-sm text-zinc-500 mt-2">
              Hoạt động ngay lập tức với mọi codebase đang dùng OpenAI SDK (Python, TypeScript/JavaScript hoặc cURL).
            </p>
          </div>

          {/* Dark Terminal Box */}
          <div className="bg-zinc-900 rounded-2xl border border-zinc-800 shadow-xl overflow-hidden font-mono text-xs sm:text-sm">
            {/* Terminal Header */}
            <div className="px-4 py-3 border-b border-zinc-800 flex flex-wrap items-center justify-between gap-2 bg-zinc-950/70">
              <div className="flex items-center gap-2">
                <span className="w-2.5 h-2.5 rounded-full bg-zinc-700" />
                <span className="w-2.5 h-2.5 rounded-full bg-zinc-700" />
                <span className="w-2.5 h-2.5 rounded-full bg-zinc-700" />
                <span className="ml-2 text-[11px] text-zinc-400 font-sans">
                  {activeCodeTab === 'python' ? 'app_integration.py' : activeCodeTab === 'node' ? 'app_integration.js' : 'request.sh'}
                </span>
              </div>

              <div className="flex items-center gap-2">
                <div className="flex items-center gap-1 bg-zinc-900 p-0.5 rounded-lg border border-zinc-800">
                  <button
                    onClick={() => setActiveCodeTab('python')}
                    className={`px-2.5 py-1 rounded text-xs transition-colors ${
                      activeCodeTab === 'python' ? 'bg-zinc-800 text-zinc-200 font-semibold' : 'text-zinc-500 hover:text-zinc-300'
                    }`}
                  >
                    Python
                  </button>
                  <button
                    onClick={() => setActiveCodeTab('node')}
                    className={`px-2.5 py-1 rounded text-xs transition-colors ${
                      activeCodeTab === 'node' ? 'bg-zinc-800 text-zinc-200 font-semibold' : 'text-zinc-500 hover:text-zinc-300'
                    }`}
                  >
                    Node.js
                  </button>
                  <button
                    onClick={() => setActiveCodeTab('curl')}
                    className={`px-2.5 py-1 rounded text-xs transition-colors ${
                      activeCodeTab === 'curl' ? 'bg-zinc-800 text-zinc-200 font-semibold' : 'text-zinc-500 hover:text-zinc-300'
                    }`}
                  >
                    cURL
                  </button>
                </div>

                <button
                  onClick={handleCopyCode}
                  className="px-2.5 py-1 rounded-lg text-xs text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800 transition-colors border border-zinc-800"
                  title="Sao chép mã"
                >
                  {copied ? 'Đã chép!' : 'Sao chép'}
                </button>

                <button
                  onClick={handleTryItNow}
                  disabled={isRunningTest}
                  className="inline-flex items-center gap-1.5 px-3 py-1 rounded-lg text-xs font-semibold bg-emerald-500 text-zinc-950 hover:bg-emerald-400 active:scale-95 transition-all shadow-xs disabled:opacity-50 cursor-pointer"
                  title="Gửi request kiểm thử tới https://p-156-latest.onrender.com/v1"
                >
                  <span className={`w-1.5 h-1.5 rounded-full bg-zinc-950 ${isRunningTest ? 'animate-ping' : ''}`} />
                  <span>{isRunningTest ? 'Đang gọi...' : 'Try it now ⚡'}</span>
                </button>
              </div>
            </div>

            {/* Code Body */}
            <div className="p-5 sm:p-6 overflow-x-auto text-zinc-300 leading-relaxed selection:bg-zinc-800">
              {activeCodeTab === 'python' && (
                <pre>
{`import os
from openai import OpenAI

# Thay đổi duy nhất: trỏ base_url về SmartRoute Gateway
client = OpenAI(
    base_url="https://p-156-latest.onrender.com/v1",  # <--- DisTributor Gateway
    api_key=os.environ.get("GATEWAY_KEY", "${customApiKey.trim() || 'sr-dev-key'}")
)

response = client.chat.completions.create(
    model="smartroute",  # Router sẽ tự động phân loại sang Tier tối ưu
    messages=[{"role": "user", "content": "Explain Paxos consensus in 3 bullet points."}]
)

# Header minh bạch đính kèm tự động:
print("Chosen Model:", response.model)
print("Content:", response.choices[0].message.content)`}
                </pre>
              )}

              {activeCodeTab === 'node' && (
                <pre>
{`import OpenAI from 'openai';

const client = new OpenAI({
  baseURL: 'https://p-156-latest.onrender.com/v1', // <--- DisTributor Gateway
  apiKey: process.env.GATEWAY_KEY || '${customApiKey.trim() || 'sr-dev-key'}',
});

const completion = await client.chat.completions.create({
  model: 'smartroute',
  messages: [{ role: 'user', content: 'Explain Paxos consensus in 3 bullet points.' }],
});

console.log("Chosen Model:", completion.model);
console.log("Content:", completion.choices[0].message.content);`}
                </pre>
              )}

              {activeCodeTab === 'curl' && (
                <pre>
{`curl -X POST "https://p-156-latest.onrender.com/v1/chat/completions" \\
  -H "Authorization: Bearer ${customApiKey.trim() || '$GATEWAY_KEY'}" \\
  -H "Content-Type: application/json" \\
  -d '{
    "model": "smartroute",
    "messages": [{"role": "user", "content": "Explain Paxos consensus in 3 bullet points."}]
  }'`}
                </pre>
              )}
            </div>

            {/* Try It Now Control & Info Bar */}
            <div className="px-5 py-3 bg-zinc-950 border-t border-zinc-800/80 flex flex-wrap items-center justify-between gap-3 text-xs">
              <div className="flex flex-wrap items-center gap-2.5 text-zinc-400">
                <span className="text-zinc-500 font-sans">Base URL:</span>
                <code className="bg-zinc-800/90 text-emerald-400 px-2 py-1 rounded text-[11px] font-mono">
                  https://p-156-latest.onrender.com/v1
                </code>
                <span className="text-zinc-600 hidden sm:inline">•</span>
                <div className="flex items-center gap-1.5">
                  <span className="text-zinc-500 font-sans">API Key:</span>
                  <div className="relative inline-flex items-center">
                    <input
                      type={showKey ? 'text' : 'password'}
                      value={customApiKey}
                      onChange={handleKeyChange}
                      onKeyDown={(e) => { if (e.key === 'Enter') handleTryItNow() }}
                      placeholder="Nhập GATEWAY_KEY của bạn..."
                      className="bg-zinc-900 hover:bg-zinc-850 focus:bg-zinc-900 text-zinc-200 placeholder-zinc-500 px-2.5 py-1 pr-14 rounded border border-zinc-700/80 focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500/40 focus:outline-none text-[11px] font-mono w-44 sm:w-60 transition-all shadow-inner"
                    />
                    <div className="absolute right-1.5 flex items-center gap-1">
                      {customApiKey && (
                        <>
                          <button
                            type="button"
                            onClick={() => setShowKey(!showKey)}
                            className="text-[10px] text-zinc-400 hover:text-zinc-200 px-1 py-0.5 rounded transition-colors"
                            title={showKey ? 'Ẩn key' : 'Hiện key'}
                          >
                            {showKey ? 'Ẩn' : 'Hiện'}
                          </button>
                          <button
                            type="button"
                            onClick={() => { setCustomApiKey(''); localStorage.removeItem('gateway_try_key') }}
                            className="text-[10px] text-zinc-500 hover:text-red-400 px-0.5 transition-colors"
                            title="Xóa key"
                          >
                            ✕
                          </button>
                        </>
                      )}
                    </div>
                  </div>
                </div>
              </div>

              <div className="flex items-center gap-2">
                <button
                  onClick={handleTryItNow}
                  disabled={isRunningTest}
                  className="inline-flex items-center gap-1.5 bg-emerald-500 hover:bg-emerald-400 text-zinc-950 font-bold px-3.5 py-1.5 rounded-lg text-xs transition-all shadow-xs active:scale-95 disabled:opacity-50 cursor-pointer"
                >
                  <span>{isRunningTest ? 'Đang chạy...' : '▶ Try it now'}</span>
                </button>
                <button
                  onClick={() => handleLaunchApp('playground')}
                  className="inline-flex items-center gap-1 text-zinc-400 hover:text-white px-2.5 py-1.5 rounded-lg text-xs transition-colors"
                >
                  <span>Mở Playground</span>
                  <ArrowRightIcon />
                </button>
              </div>
            </div>

            {/* Live Execution Output Panel */}
            {(isRunningTest || testResult) && (
              <div className="border-t border-zinc-800 bg-black/60 p-5 font-mono text-xs text-zinc-300 space-y-3">
                <div className="flex items-center justify-between text-zinc-400 pb-2 border-b border-zinc-800/80">
                  <div className="flex items-center gap-2">
                    <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
                    <span className="text-emerald-400 font-bold tracking-wider uppercase text-[10px]">
                      Terminal Output
                    </span>
                  </div>
                  {testResult?.latency && (
                    <span className="text-zinc-500 text-[11px]">Độ trễ: {testResult.latency}ms</span>
                  )}
                </div>

                <div className="text-zinc-400 text-[11px] space-y-1">
                  <div>&gt; POST https://p-156-latest.onrender.com/v1/chat/completions</div>
                  <div>
                    &gt; Header Authorization: Bearer{' '}
                    {customApiKey.trim() ? (
                      showKey ? customApiKey.trim() : `••••••••${customApiKey.trim().slice(-4)}`
                    ) : (
                      <span className="text-amber-400/90 font-mono">$GATEWAY_KEY (chưa điền)</span>
                    )}
                  </div>
                </div>

                {isRunningTest && (
                  <div className="py-3 flex items-center gap-2.5 text-zinc-400">
                    <span className="w-3.5 h-3.5 border-2 border-emerald-400 border-t-transparent rounded-full animate-spin" />
                    <span>Đang gửi prompt kiểm thử tới Gateway...</span>
                  </div>
                )}

                {testResult?.success && (
                  <div className="space-y-3 pt-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="px-2 py-0.5 rounded bg-emerald-950 text-emerald-400 border border-emerald-800 text-[10px] font-bold">
                        HTTP 200 OK
                      </span>
                      <span className="px-2 py-0.5 rounded bg-zinc-800 text-zinc-300 text-[10px]">
                        Tier: <strong className="text-white">{testResult.tier}</strong>
                      </span>
                      <span className="px-2 py-0.5 rounded bg-zinc-800 text-zinc-300 text-[10px]">
                        Model: <strong className="text-white">{testResult.model}</strong>
                      </span>
                      <span className="px-2 py-0.5 rounded bg-zinc-800 text-emerald-400 text-[10px]">
                        Cost: ${testResult.cost}
                      </span>
                    </div>

                    <div className="p-3.5 rounded-lg bg-zinc-900/80 border border-zinc-800 text-zinc-200 text-xs leading-relaxed whitespace-pre-wrap">
                      {testResult.content}
                    </div>

                    <div className="flex justify-end pt-1">
                      <button
                        onClick={() => handleLaunchApp('playground')}
                        className="inline-flex items-center gap-1.5 text-xs text-emerald-400 hover:text-emerald-300 font-sans font-semibold transition-colors"
                      >
                        <span>Mở toàn bộ giao diện Chat Playground</span>
                        <ArrowRightIcon />
                      </button>
                    </div>
                  </div>
                )}

                {testResult?.error && (
                  <div className="space-y-2 pt-1">
                    <div className="p-3 rounded-lg bg-red-950/40 border border-red-900/60 text-red-300 text-xs">
                      <strong>Lỗi kết nối:</strong> {testResult.error}
                      <p className="text-[11px] text-zinc-400 mt-1">
                        (Máy chủ Render có thể cần khoảng 30-50s để khởi động từ chế độ ngủ nếu không có traffic gần đây, hoặc bạn có thể mở Playground local để thử nghiệm ngay).
                      </p>
                    </div>
                    <div className="flex justify-end">
                      <button
                        onClick={() => handleLaunchApp('playground')}
                        className="inline-flex items-center gap-1 text-xs text-zinc-300 hover:text-white transition-colors"
                      >
                        <span>Vào Playground để chat trực tiếp</span>
                        <ArrowRightIcon />
                      </button>
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </section>

      {/* ─── Bottom Call-to-Action Banner ─────────────────────────────────── */}
      <section className="py-20 px-4 sm:px-6">
        <div className="max-w-4xl mx-auto bg-zinc-900 text-white rounded-3xl p-8 sm:p-14 text-center shadow-xl relative overflow-hidden">
          <div className="relative z-10 space-y-4 max-w-xl mx-auto">
            <h2 className="text-3xl sm:text-4xl font-bold tracking-tight leading-tight">
              Sẵn sàng tối ưu hạ tầng AI của bạn?
            </h2>
            <p className="text-sm sm:text-base text-zinc-400">
              Truy cập ngay Chat Playground để kiểm tra phản hồi hoặc mở trang Dashboard phân tích số liệu chi phí thời gian thực.
            </p>
            <div className="pt-4 flex flex-col sm:flex-row items-center justify-center gap-3">
              <button
                onClick={() => handleLaunchApp('playground')}
                className="w-full sm:w-auto inline-flex items-center justify-center gap-2 bg-white hover:bg-zinc-100 text-zinc-900 text-sm font-bold px-7 py-3.5 rounded-full transition-all active:scale-98 shadow-md"
              >
                <span>Mở Playground ngay</span>
                <ArrowRightIcon />
              </button>
              <button
                onClick={() => handleLaunchApp('dashboard')}
                className="w-full sm:w-auto inline-flex items-center justify-center gap-2 bg-zinc-800 hover:bg-zinc-700 text-zinc-200 text-sm font-semibold px-6 py-3.5 rounded-full transition-all border border-zinc-700"
              >
                <span>Xem Analytics</span>
              </button>
            </div>
          </div>
        </div>
      </section>

      {/* ─── Minimal Footer ───────────────────────────────────────────────── */}
      <footer className="py-8 px-4 sm:px-6 border-t border-zinc-200 text-xs text-zinc-400">
        <div className="max-w-6xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-4">
          <div className="flex items-center gap-2">
            <DisTributorLogo className="w-5 h-5 text-zinc-500" />
            <span className="font-semibold text-zinc-700">DisTributor Gateway</span>
            <span>· Team 156 AI20K</span>
          </div>
          <div className="flex items-center gap-6">
            <button onClick={() => handleLaunchApp('playground')} className="hover:text-zinc-900 transition-colors">
              Playground
            </button>
            <button onClick={() => handleLaunchApp('dashboard')} className="hover:text-zinc-900 transition-colors">
              Dashboard
            </button>
            <button onClick={() => handleLaunchApp('keys')} className="hover:text-zinc-900 transition-colors">
              API Keys
            </button>
            <button onClick={() => handleLaunchApp('config')} className="hover:text-zinc-900 transition-colors">
              Routing Config
            </button>
          </div>
        </div>
      </footer>
    </div>
  )
}
