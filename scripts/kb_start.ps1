$ErrorActionPreference = "SilentlyContinue"

Write-Host "正在启动知识库四件套..." -ForegroundColor Cyan

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
$meiliPort = 9011
$servePort = 8011

$env:MEILI_MASTER_KEY = $meiliKey
$env:OPENCODE_API_KEY = $apiKey
$env:PYTHONIOENCODING = "utf-8"

if (-not (Get-Process ollama -ErrorAction SilentlyContinue)) {
    Start-Process -FilePath $ollamaExe -ArgumentList "serve" -RedirectStandardOutput (Join-Path $logDir "ollama.out.log") -RedirectStandardError (Join-Path $logDir "ollama.err.log") -WindowStyle Hidden
    Write-Host "  [启动] Ollama" -ForegroundColor Green
} else {
    Write-Host "  [已运行] Ollama" -ForegroundColor DarkGray
}

if (-not (Get-Process meilisearch -ErrorAction SilentlyContinue)) {
    Start-Process -FilePath $meiliExe -ArgumentList "--db-path", "D:\SecurityKB\meta\meili", "--master-key", $meiliKey, "--http-addr", "127.0.0.1:$meiliPort" -RedirectStandardOutput (Join-Path $logDir "meili.out.log") -RedirectStandardError (Join-Path $logDir "meili.err.log") -WindowStyle Hidden
    Write-Host "  [启动] Meilisearch (端口 $meiliPort)" -ForegroundColor Green
} else {
    Write-Host "  [已运行] Meilisearch" -ForegroundColor DarkGray
}

$daemon = Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" | Where-Object { $_.CommandLine -like "*seckb daemon*" }
if (-not $daemon) {
    Start-Process -FilePath $python -ArgumentList "-m", "seckb", "daemon" -WorkingDirectory $repo -RedirectStandardOutput (Join-Path $logDir "daemon.out.log") -RedirectStandardError (Join-Path $logDir "daemon.err.log") -WindowStyle Hidden
    Write-Host "  [启动] seckb 守护进程" -ForegroundColor Green
} else {
    Write-Host "  [已运行] seckb 守护进程" -ForegroundColor DarkGray
}

$serve = Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" | Where-Object { $_.CommandLine -like "*seckb serve*" }
if (-not $serve) {
    Start-Process -FilePath $python -ArgumentList "-m", "seckb", "serve", "--port", "$servePort" -WorkingDirectory $repo -RedirectStandardOutput (Join-Path $logDir "serve.out.log") -RedirectStandardError (Join-Path $logDir "serve.err.log") -WindowStyle Hidden
    Write-Host "  [启动] 看板服务 (http://127.0.0.1:$servePort)" -ForegroundColor Green
} else {
    Write-Host "  [已运行] 看板服务" -ForegroundColor DarkGray
}

Start-Sleep -Seconds 6
$meiliStatus = "不可用"
$ollamaStatus = "不可用"
$serveStatus = "不可用"
try {
    $health = Invoke-RestMethod -Uri "http://127.0.0.1:$meiliPort/health" -TimeoutSec 5
    $meiliStatus = $health.status
} catch {}
try {
    Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 5 | Out-Null
    $ollamaStatus = "可用"
} catch {}
try {
    $h = Invoke-RestMethod -Uri "http://127.0.0.1:$servePort/health" -TimeoutSec 5
    $serveStatus = $h.status
} catch {}
$daemonCount = (Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" | Where-Object { $_.CommandLine -like "*seckb daemon*" } | Measure-Object).Count

Write-Host ""
Write-Host "Ollama: $ollamaStatus  |  Meilisearch: $meiliStatus  |  daemon: $(if ($daemonCount -gt 0) { '运行中' } else { '未运行' })  |  看板: $serveStatus" -ForegroundColor Cyan
Write-Host "知识库已就绪：看板 http://127.0.0.1:$servePort （自动采集/富化/向量/索引在后台接管）" -ForegroundColor Cyan
