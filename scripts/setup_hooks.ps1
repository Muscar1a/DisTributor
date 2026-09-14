# Install git pre-push hook for AI log submission (Windows PowerShell).
# Run once after cloning: powershell -ExecutionPolicy Bypass -File scripts\setup_hooks.ps1

$ErrorActionPreference = 'Stop'

$HookFile = '.git/hooks/pre-push'

# Git on Windows runs hooks via Git Bash, so the hook body must be bash.
# NOTE: use `#!/bin/bash` (resolved by Git for Windows to its own bash) instead of
# `#!/usr/bin/env bash`, because on Windows `env bash` picks up the WSL stub at
# C:\WINDOWS\system32\bash.exe which cannot spawn the hook.
# Also: do NOT use `Set-Content -Encoding UTF8` here — PowerShell 5.1 writes a UTF-8
# BOM, and a BOM before the shebang makes git fail with "cannot spawn pre-push".
$HookBody = @'
#!/bin/bash
# Pre-push: sweep recent Antigravity / Gemini prompts, then submit AI logs.
bash scripts/_pyrun.sh scripts/log_antigravity.py --auto || true
bash scripts/_pyrun.sh scripts/submit_log.py || true
exit 0
'@

# Write without BOM (UTF8Encoding $false) so the shebang is at byte 0.
[System.IO.File]::WriteAllText((Resolve-Path '.').Path + '/' + $HookFile, $HookBody, (New-Object System.Text.UTF8Encoding($false)))
Write-Host "[ai-log] Git pre-push hook installed."

if (-not (Test-Path .ai-log)) { New-Item -ItemType Directory -Path .ai-log | Out-Null }
if (-not (Test-Path .ai-log/.gitkeep)) { New-Item -ItemType File -Path .ai-log/.gitkeep | Out-Null }

Write-Host "[ai-log] Setup complete. Configure AI_LOG_SERVER in your .env file."
