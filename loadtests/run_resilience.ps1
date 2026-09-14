$ErrorActionPreference = 'Stop'
$hostUrl = 'https://p-156-staging.onrender.com'
$adminKey = $env:STAGING_ADMIN_KEY
if ([string]::IsNullOrWhiteSpace($adminKey)) {
    $line = Get-Content (Join-Path $PSScriptRoot '../../../.env') | Where-Object { $_ -match '^STAGING_ADMIN_KEY=' } | Select-Object -Last 1
    $adminKey = ($line -split '=', 2)[1].Trim().Trim('"').Trim("'")
}
$adminHeaders = @{ 'X-Admin-Key' = $adminKey }
$created = Invoke-RestMethod -Method Post -Uri "$hostUrl/admin/keys" -Headers $adminHeaders -ContentType 'application/json' -Body (@{ name = "judge-resilience-$(Get-Date -Format yyyyMMdd-HHmmss)"; rate_limit_per_min = 100 } | ConvertTo-Json)
$headers = @{ Authorization = "Bearer $($created.key)" }
$payload = @{ model = 'auto'; messages = @(@{ role = 'user'; content = 'Hi' }); max_tokens = 1; stream = $false; smartroute = @{ force_model = 'mock-cheap' } }
function Probe([string]$name, [string]$content, [int]$expectedMin, [int]$expectedMax) {
    $body = $payload | ConvertTo-Json -Depth 5
    $started = [Diagnostics.Stopwatch]::StartNew()
    try {
        $response = Invoke-WebRequest -Method Post -Uri "$hostUrl/v1/chat/completions" -Headers $headers -ContentType 'application/json' -Body $body -TimeoutSec 45
        $status = [int]$response.StatusCode
        $json = $response.Content | ConvertFrom-Json
        $code = $json.error.code
    } catch {
        $status = if ($_.Exception.Response) { [int]$_.Exception.Response.StatusCode } else { -1 }
        $code = ''
    }
    $started.Stop()
    [pscustomobject]@{ name = $name; status = $status; expected = "$expectedMin-$expectedMax"; code = $code; latency_ms = $started.ElapsedMilliseconds; passed = ($status -ge $expectedMin -and $status -le $expectedMax) }
}
$outcomes = @()
$payload.messages[0].content = '#force_429'; $outcomes += Probe 'forced provider 429' '#force_429' 502 502
$payload.messages[0].content = '#force_500'; $outcomes += Probe 'forced provider 500' '#force_500' 502 502
1..5 | ForEach-Object { $outcomes += Probe "circuit trigger $_" '#force_500' 400 502 }
$payload.messages[0].content = 'Hi'; $payload.smartroute.force_model = 'mock-mid'; $outcomes += Probe 'unaffected model' 'Hi' 200 200
$payload.smartroute.force_model = 'mock-cheap'; $outcomes += Probe 'cheap model while open' 'Hi' 400 502
$outcomes | Format-Table -AutoSize
Write-Host 'Waiting 300 seconds for circuit recovery...'
1..30 | ForEach-Object { Start-Sleep -Seconds 10 }
$payload.smartroute.force_model = 'mock-cheap'; $outcomes += Probe 'cheap model after recovery' 'Hi' 200 200
$outcomes | ConvertTo-Json -Depth 4 | Set-Content (Join-Path $PSScriptRoot 'results/judge/resilience.json')
Invoke-RestMethod -Method Delete -Uri "$hostUrl/admin/keys/$($created.id)" -Headers $adminHeaders | Out-Null
Write-Host 'Resilience key revoked.'
