# 自动更新 CodeGraph 索引（增量同步代码变更）
# 用法: powershell -ExecutionPolicy Bypass -File .\update_codegraph.ps1
$ErrorActionPreference = 'Stop'

$project = Split-Path -Parent $MyInvocation.MyCommand.Path

if (-not (Get-Command codegraph -ErrorAction SilentlyContinue)) {
    Write-Host "未找到 codegraph 命令，请先安装: npm i -g @colbymchenry/codegraph" -ForegroundColor Red
    exit 1
}

Write-Host "正在同步 CodeGraph 索引: $project" -ForegroundColor Cyan
codegraph sync $project
if ($LASTEXITCODE -eq 0) {
    Write-Host "CodeGraph 索引已更新" -ForegroundColor Green
} else {
    Write-Host "CodeGraph 同步失败 (exit code: $LASTEXITCODE)" -ForegroundColor Red
    exit $LASTEXITCODE
}
