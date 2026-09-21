$ErrorActionPreference = "SilentlyContinue"

Write-Host "正在启动知识库三件套..." -ForegroundColor Cyan

$authPath = Join-Path $env:USERPROFILE ".local\share\opencode\auth.json"
$apiKey = ""
if (Test-Path -LiteralPath $authPath) {
    $apiKey = (Get-Content -LiteralPath $authPath -Raw | ConvertFrom-Json).'opencode-go'.key
}
$meiliKey = [Environment]::GetEnvironmentVariable('MEILI_MASTER_KEY', 'User')

$repo = "D:\HZR_PROJECTS\seckb"
$python = Join-Path $repo ".venv\Scripts\python.exe"
$meiliExe = "D:\SecurityKB\meta\bin\meilisearch.exe"
$ollamaExe = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"
$logDir = "D:\SecurityKB\meta\logs"

if (-not (Get-Process ollama -ErrorAction SilentlyContinue)) {
    Start-Process -FilePath $ollamaExe -ArgumentList "serve" -WindowStyle Hidden
    Write-Host "  [启动] Ollama" -ForegroundColor Green
} else {
    Write-Host "  [已运行] Ollama" -ForegroundColor DarkGray
}

if (-not (Get-Process meilisearch -ErrorAction SilentlyContinue)) {
    Start-Process -FilePath $meiliExe -ArgumentList "--db-path", "D:\SecurityKB\meta\meili", "--master-key", $meiliKey, "--http-addr", "127.0.0.1:7700" -WindowStyle Hidden
    Write-Host "  [启动] Meilisearch" -ForegroundColor Green
} else {
    Write-Host "  [已运行] Meilisearch" -ForegroundColor DarkGray
}

$daemon = Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" | Where-Object { $_.CommandLine -like "*seckb daemon*" }
if (-not $daemon) {
    $env:MEILI_MASTER_KEY = $meiliKey
    $env:OPENCODE_API_KEY = $apiKey
    $env:PYTHONIOENCODING = "utf-8"
    Start-Process -FilePath $python -ArgumentList "-m", "seckb", "daemon" -WorkingDirectory $repo -RedirectStandardOutput (Join-Path $logDir "daemon.out.log") -RedirectStandardError (Join-Path $logDir "daemon.err.log") -WindowStyle Hidden
    Write-Host "  [启动] seckb 守护进程" -ForegroundColor Green
} else {
    Write-Host "  [已运行] seckb 守护进程" -ForegroundColor DarkGray
}

Start-Sleep -Seconds 6
$meiliStatus = "不可用"
$ollamaStatus = "不可用"
try {
    $health = Invoke-RestMethod -Uri "http://127.0.0.1:7700/health" -TimeoutSec 5
    $meiliStatus = $health.status
} catch {}
try {
    Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 5 | Out-Null
    $ollamaStatus = "可用"
} catch {}
$daemonCount = (Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" | Where-Object { $_.CommandLine -like "*seckb daemon*" } | Measure-Object).Count

Write-Host ""
Write-Host "Ollama: $ollamaStatus  |  Meilisearch: $meiliStatus  |  daemon: $(if ($daemonCount -gt 0) { '运行中' } else { '未运行' })" -ForegroundColor Cyan
Write-Host "知识库已就绪（自动采集/富化/向量/索引全部在后台接管）" -ForegroundColor Cyan
