$ErrorActionPreference = "SilentlyContinue"

Write-Host "正在启动知识库四件套..." -ForegroundColor Cyan

$authPath = Join-Path $env:USERPROFILE ".local\share\opencode\auth.json"
# 优先用用户环境变量的 key；仅在缺失时才回退 auth.json。
# 旧逻辑无条件覆盖，auth.json 不存在时会把 key 清成空串，导致 daemon 富化静默跳过。
$apiKey = [Environment]::GetEnvironmentVariable('OPENCODE_API_KEY', 'User')
if (-not $apiKey -and (Test-Path -LiteralPath $authPath)) {
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

# 本机 Env: 驱动器存在 Path/PATH 重复键，Start-Process 复制环境字典时会抛
# "已添加项。字典中的关键字:Path"，而 $ErrorActionPreference=SilentlyContinue 会吞掉异常，
# 造成"显示已启动、实际没进程"。统一改用 Python detached spawn。
$spawn = Join-Path $repo "scripts\spawn.py"
$daemonCtl = Join-Path $repo "scripts\daemon_ctl.py"

$env:MEILI_MASTER_KEY = $meiliKey
$env:OPENCODE_API_KEY = $apiKey
$env:PYTHONIOENCODING = "utf-8"

if (-not (Get-Process ollama -ErrorAction SilentlyContinue)) {
    & $python $spawn --out "$logDir\ollama.out.log" --err "$logDir\ollama.err.log" -- $ollamaExe serve | Out-Null
    Write-Host "  [启动] Ollama" -ForegroundColor Green
} else {
    Write-Host "  [已运行] Ollama" -ForegroundColor DarkGray
}

if (-not (Get-Process meilisearch -ErrorAction SilentlyContinue)) {
    & $python $spawn --out "$logDir\meili.out.log" --err "$logDir\meili.err.log" -- `
        $meiliExe --db-path "D:\SecurityKB\meta\meili" --master-key $meiliKey --http-addr "127.0.0.1:$meiliPort" | Out-Null
    Write-Host "  [启动] Meilisearch (端口 $meiliPort)" -ForegroundColor Green
} else {
    Write-Host "  [已运行] Meilisearch" -ForegroundColor DarkGray
}

& $python $daemonCtl status | Out-Null
if ($LASTEXITCODE -ne 0) {
    & $python $daemonCtl start --api-key $apiKey
    Write-Host "  [启动] seckb 守护进程" -ForegroundColor Green
} else {
    Write-Host "  [已运行] seckb 守护进程" -ForegroundColor DarkGray
}

$serve = Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" | Where-Object { $_.CommandLine -like "*seckb serve*" }
if (-not $serve) {
    & $python $spawn --out "$logDir\serve.out.log" --err "$logDir\serve.err.log" -- `
        $python -m seckb serve --port $servePort | Out-Null
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
