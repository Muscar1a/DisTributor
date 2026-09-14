# Judge benchmark

The judge benchmark separates expected API rejections from system failures and provisions a fresh staging key for every capacity stage so the daily token quota does not contaminate concurrency results.

Run only with explicit authorization:

```powershell
$env:SR_BENCHMARK_PYTHON = "D:\AI_ThucChien_Build\.venv\Scripts\python.exe"
& $env:SR_BENCHMARK_PYTHON loadtests/run_judge_benchmark.py
```

The runner reads `STAGING_ADMIN_KEY` from the process environment or the workspace-root `.env`, never prints it, and revokes every temporary key in a `finally` block.
