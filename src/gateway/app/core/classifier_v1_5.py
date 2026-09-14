"""ClassifierV1.5Heuristic — band-based coding difficulty classifier (doc 09).

Key changes from v1:
- Text zoning: instruction vs artifact (§4) — syntax regex on artifact only,
  intent regex on instruction only.
- Three coding bands C1/C2/C3 with base scores and floor (§5–6).
- Modifiers capped at 18, can never change tier (§6.1).
- `length` removed from coding branch entirely (§6.2).
- Fixed fast-path: coding tasks never enter fast-path (§6.5).
- Fixed regex: math expr, multi_step question counting (§6.4).

Contract B.2 preserved: no raise, no I/O, self-cuts at ROUTER_TIMEOUT_MS.
"""

import re
import time

from src.gateway.app.config.loader import load_gateway_settings

from .interfaces import BaseClassifier, ClassificationResult, Message, Signal, Tier
from .zoning import split_zones

CLASSIFIER_VERSION = "heuristic-v1.5"

FALLBACK_TIER = Tier.T2
FALLBACK_SCORE = 45

DEFAULT_T1_MAX = 30
DEFAULT_T2_MAX = 60
DEFAULT_ROUTER_TIMEOUT_MS = 800

LONG_CONTEXT_TOKENS = 2_000
FAST_PATH_MAX_WORDS = 8
SHORT_CODING_MAX_WORDS = 15
MODIFIER_CAP = 18

# --- Band base / floor (§6.1) ------------------------------------------------

_BAND_C1_BASE = 8
_BAND_C2_BASE = 32
_BAND_C2_FLOOR = 30
_BAND_C3_BASE = 62
_BAND_C3_FLOOR = 60

# --- Lexicons: Drivers D1–D6 (instruction zone, §5.1) ------------------------

_DRIVER_D1_RE = re.compile(
    r"\b(race\s*condition|deadlock|livelock|mutex|lock(?:ing|s)?"
    r"|thread[\s-]*safe|thread(?:s|ing|ed)?|goroutine|atomic|memory\s*ordering"
    r"|flaky(?:\s*test)?|intermittent|tranh\s*ch[aấ]p|tranh\s*chap"
    r"|[dđ][oồ]ng\s*th[oờ]i|dong\s*thoi"
    r"|data\s*race|semaphore|concurrent|synchroniz)"
    r"\b",
    re.IGNORECASE,
)

_DRIVER_D2_RE = re.compile(
    r"\b(quy\s*ho[aạ]ch\s*[dđ][oộ]ng|quy\s*hoach\s*dong"
    r"|dynamic\s*programming|\bDP\b|graph\s*algorithm"
    r"|[dđ][oồ]\s*th[iị]|do\s*thi|[dđ][eệ]\s*quy|de\s*quy|recursion|recursive"
    r"|invariant|ch[uứ]ng\s*minh\s*[dđ][uú]ng|chung\s*minh\s*dung"
    r"|[dđ][oộ]\s*ph[uứ]c\s*t[aạ]p|do\s*phuc\s*tap|complexity"
    r"|\bO\s*\(\s*[nNlL]|NP[\s-]*(hard|complete)"
    r"|t[oố]i\s*[uư]u\s*thu[aậ]t\s*to[aá]n|toi\s*uu\s*thuat\s*toan)"
    r"\b",
    re.IGNORECASE,
)
# guard D2: using a library ("sort danh sách", "dùng heapq")
_GUARD_D2_RE = re.compile(
    r"\b(sort\s*(danh\s*s[aá]ch|list|array)|d[uù]ng\s*(heapq|numpy|scipy|collections))\b",
    re.IGNORECASE,
)

_CONCEPT_EXPLAIN_RE = re.compile(
    r"(?:b[aạ]n\s*)?(?:h[aã]y\s*)?(?:n[oó]i\s*(?:cho\s*t[oô]i\s*)?v[eề]|noi\s*(?:cho\s*toi\s*)?ve"
    r"|gi[oớ]i\s*thi[eệ]u\s*v[eề]|gioi\s*thieu\s*ve|t[oổ]ng\s*quan\s*v[eề]|tong\s*quan\s*ve"
    r"|gi[aả]i\s*th[ií]ch\s*(?:kh[aá]i\s*ni[eệ]m\s*|thu[aậ]t\s*to[aá]n\s*)?|giai\s*thich"
    r"|kh[aá]i\s*ni[eệ]m\s*v[eề]|khai\s*niem\s*ve|tell\s*me\s*about"
    r"|explain\s*(?:the\s+concept\s+of\s+|what\s+is\s+|algorithm\s+)?|what\s*is\s*(?:a\s+|an\s+)?|what\s*are\s*)"
    r"|(\b(?:l[aà]|la)\s*g[iì]\b|\b(?:ngh[iĩ]a|nghia)\s*l[aà]\s*g[iì]\b|\bwhat\s*does\s+.*\s+mean\b)",
    re.IGNORECASE,
)

_IMPLEMENTATION_ACTION_RE = re.compile(
    r"\b(vi[eế]t\s*code|viet\s*code|vi[eế]t\s*h[aà]m|viet\s*ham|c[aà]i\s*[dđ][aặ]t|cai\s*dat|l[aậ]p\s*tr[iì]nh|lap\s*trinh"
    r"|gi[aả]i\s*b[aà]i|giai\s*bai|implement|solve|code|build|debug|fix|s[uử]a\s*l[oỗ]i|sua\s*loi"
    r"|t[oố]i\s*[uư]u|toi\s*uu|optimize|refactor|benchmark|profile)\b",
    re.IGNORECASE,
)

_DRIVER_D3_RE = re.compile(
    r"\b(ch[aậ]m|cham|slow|timeout|bottleneck|memory\s*leak|OOM|profil"
    r"|t[oố]i\s*[uư]u|toi\s*uu|optimize|performance|latency|lag)"
    r"\b",
    re.IGNORECASE,
)
# guard D3: must have evidence (numbers, units)
_EVIDENCE_D3_RE = re.compile(
    r"(\d+\s*(ms|[sS]|seconds?|gi[aâ]y|giay|ph[uú]t|phut|minutes?)"
    r"|\d+\s*(rows?|d[oò]ng|dong|records?|items?|entries)"
    r"|p\d{2,3}\b|\d+\s*MB|\d+\s*GB)",
    re.IGNORECASE,
)

_DRIVER_D4_RE = re.compile(
    r"\b(thi[eế]t\s*k[eế]\s*h[eệ]\s*th[oố]ng|thiet\s*ke\s*he\s*thong"
    r"|system\s*design|ki[eế]n\s*tr[uú]c|kien\s*truc|architecture"
    r"|migration|schema\s*design|microservice|distributed|consensus"
    r"|event\s*sourcing|refactor\s+.{0,20}(module|file|service|package)"
    r"|rate\s*limiter|[Rr]aft|[Pp]axos|CQRS|saga\s*pattern"
    r"|multi[\s-]*tenant|thi[eế]t\s*k[eế]\s*schema|thiet\s*ke\s*schema"
    r"|design\s*schema|sharding|replication|scalab)"
    r"\b",
    re.IGNORECASE,
)

_DRIVER_D5_RE = re.compile(
    r"(kh[oô]ng\s*bi[eế]t\s*t[aạ]i\s*sao|khong\s*biet\s*tai\s*sao"
    r"|[dđ][aã]\s*th[uử]\s*.*v[aẫ]n\s*l[oỗ]i|da\s*thu\s*.*van\s*loi"
    r"|ch[iỉ]\s*x[aả]y\s*ra\s*tr[eê]n\s*prod|chi\s*xay\s*ra\s*tren\s*prod"
    r"|heisenbug|l[uú]c\s*[dđ][uư][oợ]c\s*l[uú]c\s*kh[oô]ng"
    r"|luc\s*duoc\s*luc\s*khong"
    r"|don'?t\s*know\s*why|no\s*idea\s*why|can'?t\s*(figure\s*out|reproduce|repro)"
    r"|tried\s*everything|still\s*(fail|broken|wrong|crash)"
    r"|only\s*(on|in)\s*prod|works?\s*sometimes|intermittent(?:ly)?"
    r"|sometimes\s*works?\s*sometimes\s*doesn'?t"
    r"|randomly\s*(fail|crash|break))",
    re.IGNORECASE,
)
# guard D5: error message already pinpoints cause
_GUARD_D5_RE = re.compile(
    r"\b(SyntaxError|ImportError|NameError|ModuleNotFoundError|IndentationError"
    r"|TypeError:\s*\w+\s*is\s*not)\b",
)

_DRIVER_D6_RE = re.compile(
    r"\b(thi[eế]t\s*k[eế]|thiet\s*ke|design|ph[aâ]n\s*t[ií]ch|phan\s*tich|analyz)"
    r"\b.*\b(crypto|threat\s*model|auth\s*scheme|token\s*rotation"
    r"|ACID|transaction\s*isolation|l[aà]m\s*tr[oò]n\s*ti[eề]n|lam\s*tron\s*tien"
    r"|Decimal|security)",
    re.IGNORECASE,
)
# guard D6: using existing library
_GUARD_D6_RE = re.compile(
    r"\b(add|th[eê]m|them|t[ií]ch\s*h[oợ]p|tich\s*hop|integrate|install|d[uù]ng|dung|use)\b"
    r".*\b(JWT|fastapi.users|passport|bcrypt|Stripe|auth0|firebase.auth|NextAuth"
    r"|django.auth|spring.security|devise)\b",
    re.IGNORECASE,
)

# --- Lexicons: Markers M1–M5 (instruction zone, §5.2) ------------------------

_MARKER_M1_RE = re.compile(
    r"\b(format|lint|[dđ][oổ]i\s*t[eê]n|doi\s*ten|rename|docstring|comment"
    r"|type\s*hint|th[uụ]t\s*l[eề]|thut\s*le|indent|JSON\s*[↔⇔]\s*YAML"
    r"|json\s*to\s*yaml|yaml\s*to\s*json|prettify|beautify"
    r"|add\s*type\s*hints?|add\s*types?|convert\s*to|reformat"
    r"|th[eê]m\s*docstring|them\s*docstring|th[eê]m\s*comment|them\s*comment"
    r"|fix\s*indent|s[uử]a\s*th[uụ]t\s*l[eề]|sua\s*thut\s*le)\b",
    re.IGNORECASE,
)

_MARKER_M2_RE = re.compile(
    r"(th[eế]\s*n[aà]o|the\s*nao|l[aà]m\s*sao|lam\s*sao|how\s*to|how\s*do\s*I"
    r"|c[aá]ch\s*(d[uù]ng|dung|[dđ][oọ]c|doc|vi[eế]t|viet|t[aạ]o|tao)"
    r"|cach\s*(dung|doc|viet|tao)"
    r"|CRUD|boilerplate|template|scaffold|snippet|example|v[ií]\s*d[uụ]|vi\s*du)",
    re.IGNORECASE,
)

_MARKER_M3_RE = re.compile(
    r"(ngh[iĩ]a\s*l[aà]\s*g[iì]|nghia\s*la\s*gi|[lL][aà]\s*g[iì]\s*v[aậ]y|la\s*gi\s*vay"
    r"|[lL][aà]\s*g[iì]|la\s*gi"
    r"|n[oó]i\s*(?:cho\s*t[oô]i\s*)?v[eề]|noi\s*(?:cho\s*toi\s*)?ve"
    r"|gi[oớ]i\s*thi[eệ]u\s*v[eề]|gioi\s*thieu\s*ve|t[oổ]ng\s*quan\s*v[eề]|tong\s*quan\s*ve"
    r"|what\s*is\s*(a\s+|an\s+)?|what\s*are\s*(the\s+)?|what\s*does\s+\w+\s+mean|what'?s\s*the\s*difference"
    r"|kh[aá]c\s*(nhau\s*)?g[iì]|khac\s*(nhau\s*)?gi"
    r"|difference\s*between|explain\s*what|explain\s*(?:the\s+concept\s+of\s+|algorithm\s+)?|gi[aả]i\s*th[ií]ch\s*(?:kh[aá]i\s*ni[eệ]m|thu[aậ]t\s*to[aá]n)?"
    r"|giai\s*thich\s*(?:khai\s*niem|thuat\s*toan)?|tell\s*me\s*about|overview\s*of|introduction\s*to"
    r"|define\s+\w+)",
    re.IGNORECASE,
)

_MARKER_M4_RE = re.compile(
    r"\b(SyntaxError|ImportError|NameError|ModuleNotFoundError"
    r"|IndentationError|TypeError|ReferenceError)\b"
    r".*\b(line\s*\d+|d[oò]ng\s*\d+|dong\s*\d+)",
    re.IGNORECASE,
)

_MARKER_M5_RE = re.compile(
    r"\b(hello\s*world|hai\s*d[oò]ng|hai\s*dong|v[aà]i\s*d[oò]ng|vai\s*dong"
    r"|m[oộ]t\s*h[aà]m\s*nh[oỏ]|mot\s*ham\s*nho|v[ií]\s*d[uụ]\s*[dđ][oơ]n\s*gi[aả]n"
    r"|vi\s*du\s*don\s*gian|minimal|toy|cho\s*ng[uư][oờ]i\s*m[oớ]i|cho\s*nguoi\s*moi"
    r"|for\s*learning|for\s*beginners?|simple\s*example|trivial|basic\s*example"
    r"|just\s*(a\s*)?few\s*lines|small\s*script|quick\s*example|two\s*lines"
    r"|one\s*liner|single\s*function)\b",
    re.IGNORECASE,
)

# --- Intent verbs / tech nouns — determines is_coding (§5.3) -----------------

_CODING_INTENT_RE = re.compile(
    r"\b(debug|refactor|fix\b|s[uử]a\s*l[oỗ]i|sua\s*loi"
    r"|vi[eế]t\s*h[aà]m|viet\s*ham|vi[eế]t\s*code|viet\s*code"
    r"|code\s*review|unit\s*test|test|implement|deploy|compile"
    r"|build|port|migrate|optimize|profile"
    r"|l[oỗ]i|loi|error|bug|crash(?:es|ed|ing)?|exception|traceback"
    r"|b[iị]\s*l[oỗ]i|bi\s*loi|v[aẫ]n\s*l[oỗ]i|van\s*loi)\b",
    re.IGNORECASE,
)

_TECH_NOUN_RE = re.compile(
    r"\b(API|endpoint|database|SQL|schema|server|client|frontend|backend"
    r"|component|module|package|library|framework|container|docker"
    r"|kubernetes|CI/?CD|pipeline|webhook|socket|REST|GraphQL"
    r"|ORM|query|cache|queue|worker|cron|middleware"
    r"|auth|token|CORS|SSL|TLS|DNS"
    r"|algorithm"
    r"|React|Vue|Angular|Django|Flask|FastAPI|Express|Spring"
    r"|Python|JavaScript|TypeScript|Rust|Java|C\+\+"
    r"|git|branch|merge|commit|PR|pull\s*request"
    r"|h[aà]m|ham|bi[eế]n|bien|l[oớ]p|lop|giao\s*di[eệ]n|giao\s*dien)\b",
    re.IGNORECASE,
)

# --- Syntax tokens — artifact zone only (§4.1 rule inversion) ----------------

_SYNTAX_TOKEN_RE = re.compile(
    r"\b(def|class|import|from|return|SELECT|INSERT|UPDATE|DELETE"
    r"|function|const|let|var|async|await|yield|raise|throw"
    r"|struct|enum|impl|fn|pub|mod|use|trait"
    r"|interface|extends|implements|package|namespace)\b",
    re.IGNORECASE,
)

_CODE_FENCE_RE = re.compile(r"```")

# --- Non-coding signals (reused from v1, with fixes §6.4) --------------------

_MATH_KEYWORD_RE = re.compile(
    r"(ch[uứ]ng\s*minh|chung\s*minh|gi[aả]i\s*ph[uư][oơ]ng\s*tr[iì]nh|giai\s*phuong\s*trinh"
    r"|t[ií]ch\s*ph[aâ]n|tich\s*phan|[dđ][aạ]o\s*h[aà]m|dao\s*ham"
    r"|x[aá]c\s*su[aấ]t|xac\s*suat|solve|prove|integral|derivative|equation"
    r"|probability|calculate|compute)",
    re.IGNORECASE,
)
# §6.4 fix: require (a) = with digits both sides, (b) ≥2 different operators, or (c) math keyword
_MATH_EXPR_RE = re.compile(
    r"\d\s*=\s*\d"  # (a) equation with =
    r"|(?=.*\d\s*[+*/^]\s*\d)(?=.*\d\s*[-+*/^]\s*\d).*\d\s*[+\-*/^]\s*\d\s*[+\-*/^]\s*\d",  # (b) ≥2 ops
    re.IGNORECASE,
)
_MATH_SYMBOL_RE = re.compile(r"[√∫∑∏≤≥≠±∞π]")

# --- Đề thi trắc nghiệm (issue #209) -----------------------------------------
# Câu thi trắc nghiệm có cấu trúc cố định: một câu hỏi rồi tới dãy phương án đánh
# chữ cái. Nhận ra bằng regex thì tốn 0 token và gần như không sai — chat đời
# thường không ai viết bốn phương án có đánh chữ. Đo trên MMLU-Pro: bắt 415/420.
# Chọn tự động T3 vì trả lời sai một câu chuyên ngành thì model rẻ sai rất tự tin.
_MCQ_RE = re.compile(
    r"(?:^|\s)A[.)]\s.{1,400}?\sB[.)]\s.{1,400}?\sC[.)]\s.{1,400}?\sD[.)]\s"
    r"|refers to the following information",
    re.IGNORECASE | re.DOTALL,
)

# --- Math genre (doc 13 §2) --------------------------------------------------
# Chủ đề toán, KHÔNG gồm động từ chung ("solve", "compute") vì chúng cũng xuất
# hiện dày trong prompt coding — dùng chúng để nhận genre sẽ cướp nhánh coding.
_MATH_TOPIC_RE = re.compile(
    r"(ph[uư][oơ]ng\s*tr[iì]nh|phuong\s*trinh|b[aấ]t\s*[dđ][aẳ]ng\s*th[uứ]c|bat\s*dang\s*thuc"
    r"|t[ií]ch\s*ph[aâ]n|tich\s*phan|[dđ][aạ]o\s*h[aà]m|dao\s*ham|gi[oớ]i\s*h[aạ]n"
    r"|x[aá]c\s*su[aấ]t|xac\s*suat|t[oổ]\s*h[oợ]p|to\s*hop|[dđ][oồ]ng\s*d[uư]|dong\s*du"
    r"|integral|derivative|equation|inequality|probability|combinatoric|congruence"
    r"|polynomial|[dđ]a\s*th[uứ]c|da\s*thuc)",
    re.IGNORECASE,
)

# Yêu cầu ra đáp số — phân biệt bài toán thật với câu hỏi khái niệm
# ("đạo hàm là gì" không phải bài toán).
_MATH_ANSWER_INTENT_RE = re.compile(
    r"(\\boxed|final\s*answer|solve\s*for|t[ií]nh\b|tinh\b|t[ìi]m\b|tim\b"
    r"|gi[aả]i\b|giai\b|ch[uứ]ng\s*minh|chung\s*minh|compute|calculate|evaluate"
    r"|prove|find\s+(?:all|the|every|[a-z]\b))",
    re.IGNORECASE,
)

# Marker escalate T3 — doc 13 §2.3
_MH1_ADVANCED_SYMBOL_RE = re.compile(  # giải tích / đại số cao cấp
    r"(\\int|\\sum|\\prod|\\lim|\\oint|\\begin\{[a-z]*matrix\}|[∫∑∏]"
    r"|\bmatrix\b|ma\s*tr[aậ]n|ma\s*tran)",
    re.IGNORECASE,
)
_MH2_PROOF_RE = re.compile(  # yêu cầu chứng minh
    r"(\bprove\b|\bshow\s+that\b|ch[uứ]ng\s*minh|chung\s*minh)", re.IGNORECASE
)
_MH3_MODULAR_RE = re.compile(  # số học modular / tổ hợp
    r"(\\pmod|\bmod\s*\d|\bmodulo\b|\\binom|\bbinomial\b|s[oố]\s*d[uư]\b|so\s*du\b"
    r"|[dđ][oồ]ng\s*d[uư]|dong\s*du)",
    re.IGNORECASE,
)
_MH4_NESTED_RE = re.compile(  # cấu trúc lồng sâu
    r"(\\frac\{[^}]*\\frac|\\sqrt\{[^}]*\\sqrt|\\boxed\{[^}]*\\boxed)"
)
_MH5_COMPETITION_RE = re.compile(  # từ khoá thi đấu
    r"\b(olympiad|olympic|competition|AIME|IMO|Putnam|USAMO|HSG)\b", re.IGNORECASE
)
_MH6_HIGHER_POLYNOMIAL_RE = re.compile(  # đa thức / phương trình bậc ba trở lên hoặc kiểm tra nghiệm ngược
    r"(\^[3-9]|\bb[aậ]c\s*[3-9]\b|\bbac\s*[3-9]\b|\bcubic\b|\bpolynomial\b|\bph[uư][oơ]ng\s*tr[iì]nh\s*b[aậ]c\s*(?:ba|b[oố]n|n[aă]m)\b|\bth[eế]\s*ng[uư][oợ]c\b|\bthe\s*nguoc\b)",
    re.IGNORECASE,
)

# Guard §2.2 — số học vặt ("tính 15 * 23") không đáng floor T2. Nhận diện bằng
# việc KHÔNG có ẩn số: một chữ cái đứng riêng đi kèm toán tử, hoặc dạng f(x).
_MATH_VARIABLE_RE = re.compile(
    r"(?<![A-Za-z])[A-Za-z](?![A-Za-z])\s*[\^=<>+\-*/]|[A-Za-z]\s*\(\s*[A-Za-z]\s*\)"
)
ARITHMETIC_ONLY_MAX_WORDS = 12

_MULTI_STEP_RE = re.compile(
    r"(ph[aâ]n\s*t[ií]ch|phan\s*tich|so\s*s[aá]nh|so\s*sanh"
    r"|[dđ][aá]nh\s*gi[aá]|danh\s*gia|l[aậ]p\s*k[eế]\s*ho[aạ]ch|lap\s*ke\s*hoach"
    r"|t[uừ]ng\s*b[uư][oớ]c|tung\s*buoc|v[iì]\s*sao|vi\s*sao|t[aạ]i\s*sao|tai\s*sao"
    r"|step\s*by\s*step|analyze|compare|evaluate|plan\s+out|why\s+does|explain\s+why)",
    re.IGNORECASE,
)

_OUTPUT_CONSTRAINT_RE = re.compile(
    r"(json\s*schema|tr[aả]\s*v[eề]\s*json|tra\s*ve\s*json"
    r"|[dđ][uú]ng\s*[dđ][iị]nh\s*d[aạ]ng|dung\s*dinh\s*dang"
    r"|d[aạ]ng\s*b[aả]ng|dang\s*bang|markdown\s*table|as\s+json|in\s+json|csv|yaml"
    r"|[dđ][uú]ng\s*\d+\s*(t[uừ]|tu|ch[uữ]|chu|d[oò]ng|dong)"
    r"|exactly\s*\d+\s*(words|lines|bullets))",
    re.IGNORECASE,
)

_LONG_CREATIVE_RE = re.compile(
    r"(vi[eế]t\s*b[aà]i|viet\s*bai|vi[eế]t\s*truy[eệ]n|viet\s*truyen"
    r"|b[aà]i\s*lu[aậ]n|bai\s*luan|essay|short\s*story"
    r"|blog\s*post|write\s+an?\s+article)",
    re.IGNORECASE,
)
_WORD_COUNT_REQUEST_RE = re.compile(r"(\d{3,5})\s*(t[uừ]|tu|ch[uữ]|chu|words)", re.IGNORECASE)
_LONG_CREATIVE_WORDS = 500

_LENGTH_MID_TOKENS = 50
_LENGTH_LONG_TOKENS = 300

_GREETING_RE = re.compile(
    r"^\s*(hi|hello|hey|ch[aà]o|chao|xin\s*ch[aà]o|xin\s*chao|good\s*(morning|afternoon|evening)"
    r"|c[aả]m\s*[oơ]n|cam\s*on|thanks|thank\s*you|ok|okay|bye|t[aạ]m\s*bi[eệ]t|tam\s*biet)\b",
    re.IGNORECASE,
)

# --- multi_file modifier (§6.2) ----------------------------------------------

_MULTI_FILE_RE = re.compile(
    r"(to[aà]n\s*b[oộ]\s*codebase|toan\s*bo\s*codebase|across\s*the\s*codebase"
    r"|all\s*files|nhi[eề]u\s*file|nhieu\s*file|multiple\s*(files|modules))",
    re.IGNORECASE,
)
_FILE_MENTION_RE = re.compile(
    r"\b\w+\.(py|js|ts|tsx|jsx|go|rs|java|c|cpp|h|rb|php|vue|svelte|css|html|sql|yaml|yml|toml|json)\b",
    re.IGNORECASE,
)

# --- Error artifact (reuse turn_analyzer pattern) -----------------------------

_ERROR_ARTIFACT_RE = re.compile(
    r"(Traceback\s*\(most\s*recent\s*call\s*last\)"
    r'|File\s*"[^"]+",\s*line\s*\d+'
    r"|\b\w+(?:Error|Exception):"
    r"|FAILED\s+test_"
    r"|panic:"
    r"|Exception\s+in\s+thread)",
    re.IGNORECASE | re.MULTILINE,
)

# --- Genre: competitive programming (doc 10 §4.1) ----------------------------

_CP_MARKER_TIME_LIMIT = re.compile(r"time\s*limit\s*per\s*test", re.IGNORECASE)
_CP_MARKER_MEM_LIMIT = re.compile(r"memory\s*limit\s*per\s*test", re.IGNORECASE)
_CP_MARKER_TEST_CASES = re.compile(
    r"\b(the\s*number\s*of\s*test\s*cases|for\s*each\s*test\s*case)\b", re.IGNORECASE,
)
_CP_MARKER_CONSTRAINT = re.compile(
    r"[≤<]=?\s*[a-z][_,]?\s*[a-z]?\s*[≤<]=?\s*\d*\s*[·*]?\s*10\s*[\^]\s*\d",
)
_CP_MARKER_IO_SECTIONS = re.compile(
    r"^Input$.*?^Output$.*?^Examples?$", re.MULTILINE | re.DOTALL,
)

# CP C3 escalation rules (doc 10 §4.2)
_CP_LARGE_NQ_RE = re.compile(
    r"[nNmMqQ]\s*[,≤<]=?\s*\d*\s*[·*]?\s*10\s*[\^]\s*[5-9]",
)
_CP_UPDATE_RE = re.compile(
    r"\b(update|query|queries|modify|assign|change|set\s+\w+\s+to)\b", re.IGNORECASE,
)
_CP_MOD_998244353 = re.compile(r"998244353")
_CP_INTERACTIVE = re.compile(r"\binteractive\s*problem\b", re.IGNORECASE)
_CP_LARGE_CONSTRAINT = re.compile(
    r"\d*\s*[·*]?\s*10\s*[\^]\s*(?:9|1[0-8])\b",
)
_CP_HARD_TECHNIQUE = re.compile(
    r"\b(suffix\s*(?:automaton|array)|max\s*flow|matching|convex\s*hull"
    r"|heavy[- ]light|centroid\s*decomposition|segment\s*tree\s*beats"
    r"|Mo'?s?\s*algorithm|li\s*chao|FFT|NTT"
    r"|link[- ]cut\s*tree|persistent\s*(?:segment\s*tree|trie))\b",
    re.IGNORECASE,
)


def _estimate_tokens(text: str) -> int:
    if not text:
        return 0
    words = len(text.split())
    return max(int(words * 1.3), len(text) // 4)


class ClassifierV1_5Heuristic(BaseClassifier):  # noqa: N801
    """Band-based coding classifier — doc 09 §5–6.

    Band determines tier; modifiers rank within tier but never cross boundaries.
    """

    def __init__(
        self,
        t1_max: int = DEFAULT_T1_MAX,
        t2_max: int = DEFAULT_T2_MAX,
        router_timeout_ms: int | None = None,
    ) -> None:
        self.t1_max = t1_max
        self.t2_max = t2_max
        if router_timeout_ms is None:
            router_timeout_ms = load_gateway_settings().router_timeout_ms
        self.router_timeout_ms = router_timeout_ms

    async def classify(self, messages: list[Message]) -> ClassificationResult:
        started = time.perf_counter()
        try:
            score, signals = self._score(messages, started)
            tier = self._to_tier(score)
        except Exception:  # noqa: BLE001 — contract B.2
            return self._fallback(started)
        return ClassificationResult(
            score=score,
            tier=tier,
            signals=signals,
            classifier_version=CLASSIFIER_VERSION,
            latency_ms=self._elapsed_ms(started),
        )

    def _score(self, messages: list[Message], started: float) -> tuple[int, list[Signal]]:
        prompt = self._prompt_text(messages)
        context_tokens = sum(_estimate_tokens(m.content or "") for m in messages)

        instruction, artifact = split_zones(prompt)

        # Đề thi trắc nghiệm — kiểm trước mọi genre khác: cấu trúc rõ, không cần
        # đoán. Một câu thi ngắn vẫn đòi kiến thức chuyên ngành (issue #209).
        if self._detect_genre_mcq(prompt):
            signals = [Signal("genre_mcq", _BAND_C3_BASE)]
            if context_tokens > LONG_CONTEXT_TOKENS:
                signals.append(Signal("long_context", 6))
            return min(100, _BAND_C3_BASE + (6 if context_tokens > LONG_CONTEXT_TOKENS else 0)), signals

        # Genre detection (doc 10 §4.1): CP before coding/non-coding split
        if self._detect_genre_cp(prompt):
            return self._score_cp(prompt, context_tokens, started)

        # Genre math (doc 13 §2.1): sau CP, trước khi chia coding/non-coding — để
        # bài toán thuần không bị nhánh non-coding chấm theo độ dài (issue #194).
        if self._detect_genre_math(instruction, artifact):
            return self._score_math(instruction, context_tokens, started)

        is_coding = self._is_coding(instruction, artifact)

        if is_coding:
            return self._score_coding(instruction, artifact, context_tokens, started)
        return self._score_non_coding(instruction, prompt, context_tokens, started)

    # -- Coding branch (§6.1) -------------------------------------------------

    def _score_coding(
        self, instruction: str, artifact: str, context_tokens: int, started: float,
    ) -> tuple[int, list[Signal]]:
        band, band_signal = self._determine_band(instruction)
        signals: list[Signal] = [band_signal]

        base = {
            "band_c1": _BAND_C1_BASE,
            "band_c2": _BAND_C2_BASE,
            "band_c3": _BAND_C3_BASE,
        }[band_signal.name]

        floor = {
            "band_c1": 0,
            "band_c2": _BAND_C2_FLOOR,
            "band_c3": _BAND_C3_FLOOR,
        }[band_signal.name]

        # modifiers (§6.2)
        mod_total = 0
        for name, points in self._coding_modifiers(instruction, artifact, context_tokens, band_signal.name):
            signals.append(Signal(name, points))
            mod_total += points

        self._check_deadline(started)

        mod_total = min(mod_total, MODIFIER_CAP)
        score = max(base + mod_total, floor)
        score = max(0, min(100, score))

        return score, signals

    # -- CP genre (doc 10 §4.1–4.2) -------------------------------------------

    def _detect_genre_mcq(self, text: str) -> bool:
        """True nếu là câu thi trắc nghiệm (issue #209) — xem `_MCQ_RE`."""
        return bool(_MCQ_RE.search(text))

    def _detect_genre_cp(self, text: str) -> bool:
        """Return True if text is a competitive programming problem (≥2 distinct markers)."""
        hits = 0
        if _CP_MARKER_TIME_LIMIT.search(text):
            hits += 1
        if _CP_MARKER_MEM_LIMIT.search(text):
            hits += 1
        if _CP_MARKER_TEST_CASES.search(text):
            hits += 1
        if _CP_MARKER_CONSTRAINT.search(text):
            hits += 1
        if _CP_MARKER_IO_SECTIONS.search(text):
            hits += 1
        return hits >= 2

    def _score_cp(
        self, text: str, context_tokens: int, started: float,
    ) -> tuple[int, list[Signal]]:
        """Score a competitive programming problem — doc 10 §4.2.

        Bypasses M1–M5 markers and length signal entirely.
        Floor is C2 (never C1). Five rules can escalate to C3.
        """
        signals: list[Signal] = [Signal("genre_cp", 0)]

        # Check C3 escalation rules
        escalate = False
        # (a) both n and q ≥ 10^5 AND has update/query operations
        if _CP_LARGE_NQ_RE.search(text) and _CP_UPDATE_RE.search(text):
            escalate = True
        # (b) mod 998244353
        if _CP_MOD_998244353.search(text):
            escalate = True
        # (c) interactive problem
        if _CP_INTERACTIVE.search(text):
            escalate = True
        # (d) constraint ≥ 10^9
        if _CP_LARGE_CONSTRAINT.search(text):
            escalate = True
        # (e) hard technique keywords
        if _CP_HARD_TECHNIQUE.search(text):
            escalate = True

        if escalate:
            signals.append(Signal("band_c3", _BAND_C3_BASE))
            score = _BAND_C3_BASE
        else:
            signals.append(Signal("band_c2", _BAND_C2_BASE))
            score = _BAND_C2_BASE

        self._check_deadline(started)

        # Context modifier only (no M1-M5, no length)
        if context_tokens > LONG_CONTEXT_TOKENS:
            signals.append(Signal("long_context", 6))
            score += 6

        return max(0, min(100, score)), signals

    # -- Math genre (doc 13 §2) -----------------------------------------------

    def _detect_genre_math(self, instruction: str, artifact: str) -> bool:
        """True nếu instruction là bài toán cần ra đáp số — doc 13 §2.1.

        Hai điều kiện phải cùng đúng: có tín hiệu toán, VÀ có yêu cầu ra đáp số.
        Câu hỏi khái niệm ("đạo hàm là gì") thiếu vế sau nên không kích hoạt.
        """
        # Có code kèm theo thì đây là việc coding, không phải bài toán thuần.
        if _SYNTAX_TOKEN_RE.search(artifact) or _CODE_FENCE_RE.search(artifact):
            return False

        has_math = bool(
            _MATH_TOPIC_RE.search(instruction)
            or _MATH_EXPR_RE.search(instruction)
            or _MATH_SYMBOL_RE.search(instruction)
            or self._math_hard_markers(instruction)
        )
        if not has_math:
            return False
        return bool(_MATH_ANSWER_INTENT_RE.search(instruction))

    def _math_hard_markers(self, instruction: str) -> list[str]:
        """Các marker MH1–MH5 khiến bài toán được đẩy thẳng lên T3 — doc 13 §2.3."""
        hits: list[str] = []
        if _MH1_ADVANCED_SYMBOL_RE.search(instruction):
            hits.append("mh1_advanced_symbol")
        if _MH2_PROOF_RE.search(instruction):
            hits.append("mh2_proof")
        if _MH3_MODULAR_RE.search(instruction):
            hits.append("mh3_modular")
        if _MH4_NESTED_RE.search(instruction):
            hits.append("mh4_nested")
        if _MH5_COMPETITION_RE.search(instruction):
            hits.append("mh5_competition")
        if _MH6_HIGHER_POLYNOMIAL_RE.search(instruction):
            hits.append("mh6_higher_polynomial")
        return hits

    def _is_arithmetic_only(self, instruction: str) -> bool:
        """Số học vặt ("tính 15 * 23") — guard doc 13 §2.2, giữ ở C1 thay vì floor T2.

        Không ẩn số, không marker khó, và ngắn. Thiếu guard này thì "2+2 bằng mấy"
        cũng bị floor T2 và chỉ tiêu tiết kiệm chi phí lãnh đủ.
        """
        if _MATH_VARIABLE_RE.search(instruction):
            return False
        if self._math_hard_markers(instruction):
            return False
        return len(instruction.split()) <= ARITHMETIC_ONLY_MAX_WORDS

    def _score_math(
        self, instruction: str, context_tokens: int, started: float,
    ) -> tuple[int, list[Signal]]:
        """Chấm điểm bài toán thuần — doc 13 §2.2, sao đúng khuôn `_score_cp`.

        Bỏ qua M1–M5 và tín hiệu `length`. Độ khó đến từ bản chất bài toán, không
        từ độ dài lời kể — đó là §1.1 của doc 13 và là gốc của issue #194.
        """
        signals: list[Signal] = [Signal("genre_math", 0)]

        markers = self._math_hard_markers(instruction)
        if markers:
            # ≥1 marker khó → T3 thẳng. Doc 13 §1 cho thấy mini là net-âm ở math,
            # nên không dừng ở T2.
            for name in markers:
                signals.append(Signal(name, 0))
            signals.append(Signal("band_c3", _BAND_C3_BASE))
            score = _BAND_C3_BASE
        elif self._is_arithmetic_only(instruction):
            signals.append(Signal("arithmetic_only", _BAND_C1_BASE))
            score = _BAND_C1_BASE
        else:
            signals.append(Signal("band_c2", _BAND_C2_BASE))
            score = _BAND_C2_BASE

        self._check_deadline(started)

        if context_tokens > LONG_CONTEXT_TOKENS:
            signals.append(Signal("long_context", 6))
            score += 6

        return max(0, min(100, score)), signals

    def _determine_band(self, instruction: str) -> tuple[str, Signal]:
        # C3 drivers (§5.1) — checked first, highest priority
        if self._check_d1(instruction):
            return "C3", Signal("band_c3", _BAND_C3_BASE)
        if self._check_d2(instruction):
            return "C3", Signal("band_c3", _BAND_C3_BASE)
        if self._check_d3(instruction):
            return "C3", Signal("band_c3", _BAND_C3_BASE)
        if self._check_d4(instruction):
            return "C3", Signal("band_c3", _BAND_C3_BASE)
        if self._check_d5(instruction):
            return "C3", Signal("band_c3", _BAND_C3_BASE)
        if self._check_d6(instruction):
            return "C3", Signal("band_c3", _BAND_C3_BASE)

        # C1 markers (§5.2) — if no driver, check for easy markers
        if self._check_markers(instruction):
            return "C1", Signal("band_c1", _BAND_C1_BASE)

        # Short prompt without complexity signals → trivial coding task
        if len(instruction.split()) <= SHORT_CODING_MAX_WORDS:
            return "C1", Signal("band_c1", _BAND_C1_BASE)

        # C2 default
        return "C2", Signal("band_c2", _BAND_C2_BASE)

    def _check_d1(self, instruction: str) -> bool:
        return bool(_DRIVER_D1_RE.search(instruction))

    def _check_d2(self, instruction: str) -> bool:
        if not _DRIVER_D2_RE.search(instruction):
            return False
        if _GUARD_D2_RE.search(instruction):
            return False
        if _CONCEPT_EXPLAIN_RE.search(instruction) and not _IMPLEMENTATION_ACTION_RE.search(instruction):
            return False
        return True

    def _check_d3(self, instruction: str) -> bool:
        if not _DRIVER_D3_RE.search(instruction):
            return False
        return bool(_EVIDENCE_D3_RE.search(instruction))

    def _check_d4(self, instruction: str) -> bool:
        return bool(_DRIVER_D4_RE.search(instruction))

    def _check_d5(self, instruction: str) -> bool:
        if not _DRIVER_D5_RE.search(instruction):
            return False
        return not _GUARD_D5_RE.search(instruction)

    def _check_d6(self, instruction: str) -> bool:
        if not _DRIVER_D6_RE.search(instruction):
            return False
        return not _GUARD_D6_RE.search(instruction)

    def _check_markers(self, instruction: str) -> bool:
        return bool(
            _MARKER_M1_RE.search(instruction)
            or _MARKER_M2_RE.search(instruction)
            or _MARKER_M3_RE.search(instruction)
            or _MARKER_M4_RE.search(instruction)
            or _MARKER_M5_RE.search(instruction)
        )

    def _coding_modifiers(
        self, instruction: str, artifact: str, context_tokens: int, band_name: str,
    ):
        if _ERROR_ARTIFACT_RE.search(artifact):
            yield "error_artifact", 8

        artifact_tokens = _estimate_tokens(artifact)
        if artifact_tokens > 150:
            yield "artifact_large", 6

        if _MULTI_FILE_RE.search(instruction) or len(_FILE_MENTION_RE.findall(instruction)) >= 2:
            yield "multi_file", 6

        if _OUTPUT_CONSTRAINT_RE.search(instruction):
            yield "output_constraint", 6

        # multi_step only for C1/C2 (§6.2)
        if band_name in ("band_c1", "band_c2"):
            if self._multi_step_points_v15(instruction, as_modifier=True):
                yield "multi_step", 6

        if context_tokens > LONG_CONTEXT_TOKENS:
            yield "long_context", 6

    # -- Non-coding branch (§6.3 — keep v1 model, with regex fixes §6.4) ------

    def _score_non_coding(
        self, instruction: str, full_prompt: str, context_tokens: int, started: float,
    ) -> tuple[int, list[Signal]]:
        signals: list[Signal] = []
        score = 0
        prompt_tokens = _estimate_tokens(instruction)

        for name, points in (
            ("math", self._math_points_v15(instruction)),
            ("multi_step", self._multi_step_points_v15(instruction, as_modifier=False)),
            ("output_constraint", 10 if _OUTPUT_CONSTRAINT_RE.search(instruction) else 0),
            ("long_creative", self._long_creative_points(instruction)),
            ("length", self._length_points(prompt_tokens)),
            ("long_context", 10 if context_tokens > LONG_CONTEXT_TOKENS else 0),
        ):
            if points:
                signals.append(Signal(name, points))
                score += points

        self._check_deadline(started)

        # fast-path (§6.5): only when no signals detected, same as v1
        if not signals and self._is_fast_path_easy(instruction):
            return 0, [Signal("fast_path_easy", 0)]

        return max(0, min(100, score)), signals

    # -- is_coding (§5.3) -----------------------------------------------------

    def _is_coding(self, instruction: str, artifact: str) -> bool:
        if _CODING_INTENT_RE.search(instruction):
            return True
        if _TECH_NOUN_RE.search(instruction):
            return True
        if _SYNTAX_TOKEN_RE.search(artifact) or _CODE_FENCE_RE.search(artifact):
            return True
        # D1/D4 keywords are unambiguously coding; D2 partially
        if _DRIVER_D1_RE.search(instruction):
            return True
        if _DRIVER_D4_RE.search(instruction):
            return True
        if _DRIVER_D2_RE.search(instruction):
            return True
        return False

    # -- Signal detectors (fixed §6.4) ----------------------------------------

    def _math_points_v15(self, text: str) -> int:
        if _MATH_KEYWORD_RE.search(text) or _MATH_EXPR_RE.search(text) or _MATH_SYMBOL_RE.search(text):
            return 20
        return 0

    def _multi_step_points_v15(self, text: str, *, as_modifier: bool = False) -> int:
        points = 6 if as_modifier else 15
        if _MULTI_STEP_RE.search(text):
            return points
        # §6.4 fix: count real questions (≥4 words) in instruction zone
        questions = [q.strip() for q in text.split("?") if len(q.strip().split()) >= 4]
        if len(questions) >= 2:
            return points
        return 0

    def _long_creative_points(self, text: str) -> int:
        if not _LONG_CREATIVE_RE.search(text):
            return 0
        match = _WORD_COUNT_REQUEST_RE.search(text)
        if match and int(match.group(1)) > _LONG_CREATIVE_WORDS:
            return 10
        return 0

    def _length_points(self, prompt_tokens: int) -> int:
        if prompt_tokens > _LENGTH_LONG_TOKENS:
            return 18
        if prompt_tokens >= _LENGTH_MID_TOKENS:
            return 10
        return 0

    # -- Fast-path (§6.5) -----------------------------------------------------

    def _is_fast_path_easy(self, instruction: str) -> bool:
        if _GREETING_RE.search(instruction):
            return True
        return 0 < len(instruction.split()) <= FAST_PATH_MAX_WORDS

    # -- Utilities -------------------------------------------------------------

    def _to_tier(self, score: int) -> Tier:
        if score < self.t1_max:
            return Tier.T1
        if score < self.t2_max:
            return Tier.T2
        return Tier.T3

    def _prompt_text(self, messages: list[Message]) -> str:
        for message in reversed(messages or []):
            if message.role == "user" and message.content:
                return message.content
        return ""

    def _check_deadline(self, started: float) -> None:
        if self._elapsed_ms(started) > self.router_timeout_ms:
            raise TimeoutError("classifier vượt ROUTER_TIMEOUT_MS")

    def _elapsed_ms(self, started: float) -> int:
        return int((time.perf_counter() - started) * 1000)

    def _fallback(self, started: float) -> ClassificationResult:
        return ClassificationResult(
            score=FALLBACK_SCORE,
            tier=FALLBACK_TIER,
            signals=[Signal("classifier_error", 0)],
            classifier_version=CLASSIFIER_VERSION,
            latency_ms=self._elapsed_ms(started),
        )
