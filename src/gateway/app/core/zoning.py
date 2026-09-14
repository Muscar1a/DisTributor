"""Text zoning — split user message into instruction zone and artifact zone (doc 09 §4).

Artifact zone: fenced code blocks, inline code spans, indented blocks (≥3 lines
with leading whitespace/code syntax), stack trace fingerprints.
Instruction zone: everything else — the user's actual request.

Pure CPU, no I/O, no exceptions.
"""

import re

# fenced code block (``` or ~~~), greedy to closing fence or end of string (B7)
_FENCE_RE = re.compile(r"(```|~~~).*?(?:\1|$)", re.DOTALL)

# inline code spans `...`
_INLINE_CODE_RE = re.compile(r"`[^`\n]+`")

# ≥3 consecutive lines that look like code (leading whitespace + code-ish chars)
_INDENTED_BLOCK_RE = re.compile(
    r"(?:^[ \t]+\S.*\n){3,}",
    re.MULTILINE,
)

# stack trace fingerprints
_TRACE_RE = re.compile(
    r"(?:Traceback\s*\(most\s*recent\s*call\s*last\)[\s\S]*?(?:\w+(?:Error|Exception):.*$))"
    r"|(?:^\s*at\s+\S+\(.*?\)(?:\n\s*at\s+\S+\(.*?\))+)"  # Java/JS stack
    r'|(?:File\s*"[^"]+",\s*line\s*\d+[\s\S]*?(?:\w+(?:Error|Exception):.*$))',
    re.MULTILINE,
)


def split_zones(text: str) -> tuple[str, str]:
    """Return (instruction_zone, artifact_zone).

    Artifact zone = concatenation of all extracted blocks (order preserved).
    Instruction zone = remainder after stripping those blocks.
    """
    if not text:
        return "", ""

    artifacts: list[str] = []
    remaining = text

    # 1. fenced blocks first (outermost fence wins — B8)
    for m in reversed(list(_FENCE_RE.finditer(remaining))):
        artifacts.append(m.group())
        remaining = remaining[: m.start()] + remaining[m.end() :]

    # 2. stack traces (before inline code, since traces may contain backticks)
    for m in reversed(list(_TRACE_RE.finditer(remaining))):
        artifacts.append(m.group())
        remaining = remaining[: m.start()] + remaining[m.end() :]

    # 3. inline code spans
    for m in reversed(list(_INLINE_CODE_RE.finditer(remaining))):
        artifacts.append(m.group())
        remaining = remaining[: m.start()] + remaining[m.end() :]

    # 4. indented blocks (≥3 lines)
    for m in reversed(list(_INDENTED_BLOCK_RE.finditer(remaining))):
        artifacts.append(m.group())
        remaining = remaining[: m.start()] + remaining[m.end() :]

    artifact_zone = "\n".join(reversed(artifacts))
    instruction_zone = remaining.strip()

    return instruction_zone, artifact_zone
