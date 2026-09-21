$ErrorActionPreference = "SilentlyContinue"

Write-Host "正在停止知识库相关进程..." -ForegroundColor Cyan
$stopped = 0

Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" | Where-Object {
    $_.CommandLine -match "seckb (daemon|collect|enrich|embed|index|serve)" -or $_.CommandLine -match "backfill_kev_nvd"
} | ForEach-Object {
    Stop-Process -Id $_.ProcessId -Force
    $script:stopped++
    Write-Host "  [停止] seckb 任务 (PID $($_.ProcessId))" -ForegroundColor Yellow
}

foreach ($name in @("meilisearch", "ollama", "ollama app")) {
    Get-Process $name -ErrorAction SilentlyContinue | ForEach-Object {
        Stop-Process -Id $_.Id -Force
        $script:stopped++
        Write-Host "  [停止] $name (PID $($_.Id))" -ForegroundColor Yellow
    }
}

Start-Sleep -Seconds 3
$remain = (Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -match "seckb (daemon|collect|enrich|embed|index|serve)" -or $_.Name -in @("meilisearch", "ollama")
} | Measure-Object).Count

Write-Host ""
if ($remain -eq 0) {
    Write-Host "已全部停止（共 $stopped 个进程），可以安心打游戏了" -ForegroundColor Green
} else {
    Write-Host "警告：仍有 $remain 个相关进程在运行" -ForegroundColor Red
}
