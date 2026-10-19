#!/usr/bin/env pwsh
<#
.SYNOPSIS
  在这台机器上准备 yu-gi-oh-ai-tools 的运行环境。

.DESCRIPTION
  1. 用 Go 构建 ygo-db CLI（go.mod 要求 Go 1.26.1，GOTOOLCHAIN=auto 会自动下载）。
  2. 在 skills/.venv 建立 Python 虚拟环境，安装 pytest / ruff。
  3. 拉取卡牌数据库（首次运行 CLI 时自动 git clone 到 %LOCALAPPDATA%\ygo-db）。

.PARAMETER SkipGo
  跳过 Go 构建。

.PARAMETER SkipPython
  跳过 Python 虚拟环境。

.PARAMETER SkipDatabase
  跳过数据库拉取。
#>
[CmdletBinding()]
param(
  [switch]$SkipGo,
  [switch]$SkipPython,
  [switch]$SkipDatabase
)

# 原生命令（go / python / pip）会往 stderr 写进度信息，不能让它们触发终止。
$ErrorActionPreference = 'Continue'
$repo = Split-Path -Parent $PSScriptRoot

function Step($message) { Write-Host ""; Write-Host "==> $message" -ForegroundColor Cyan }
function Ok($message) { Write-Host "    $message" -ForegroundColor Green }

# ---------------------------------------------------------------- Go / CLI ---
if (-not $SkipGo) {
  Step '构建 ygo-db CLI'

  if (-not (Get-Command go -ErrorAction SilentlyContinue)) {
    Write-Host '找不到 go，请先安装 Go 1.21+ 并加入 PATH：https://go.dev/dl/' -ForegroundColor Red
    exit 1
  }

  # go.mod 声明 go 1.26.1；Go 1.21+ 在 GOTOOLCHAIN=auto 时会自动下载对应工具链。
  $env:GOTOOLCHAIN = 'auto'

  Push-Location (Join-Path $repo 'ygo-db')
  try {
    New-Item -ItemType Directory -Force -Path 'bin' | Out-Null
    go build -o 'bin\ygo-db-cli.exe' ./cmd/ygo-db-cli
    if ($LASTEXITCODE -ne 0) { Write-Host "go build 失败（exit $LASTEXITCODE）" -ForegroundColor Red; exit 1 }
    Ok "已生成 $repo\ygo-db\bin\ygo-db-cli.exe"
  }
  finally { Pop-Location }
}

# ------------------------------------------------------------------ Python ---
if (-not $SkipPython) {
  Step '配置 Python 环境 (skills/)'

  if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Host '找不到 python，请先安装 Python 3.14+ 并加入 PATH。' -ForegroundColor Red
    exit 1
  }

  $pyVersion = (& python -c "import sys; print('%d.%d' % sys.version_info[:2])" | Select-Object -First 1)
  if ([version]$pyVersion -lt [version]'3.14') {
    Write-Host "需要 Python 3.14+，当前是 $pyVersion。" -ForegroundColor Red
    exit 1
  }

  Push-Location (Join-Path $repo 'skills')
  try {
    if (-not (Test-Path '.venv\Scripts\python.exe')) {
      python -m venv .venv
      if ($LASTEXITCODE -ne 0) { Write-Host "创建虚拟环境失败（exit $LASTEXITCODE）" -ForegroundColor Red; exit 1 }
    }
    & '.\.venv\Scripts\python.exe' -m pip install --disable-pip-version-check -q "pytest>=9.0.2" ruff
    if ($LASTEXITCODE -ne 0) { Write-Host "安装依赖失败（exit $LASTEXITCODE）" -ForegroundColor Red; exit 1 }
    Ok "Python $pyVersion，依赖已就绪（skills/.venv）"
  }
  finally { Pop-Location }
}

# ---------------------------------------------------------------- Database ---
if (-not $SkipDatabase) {
  Step '检查卡牌数据库'

  $exe = Join-Path $repo 'ygo-db\bin\ygo-db-cli.exe'
  if (-not (Test-Path $exe)) {
    Write-Host '    未找到 CLI，请先运行不带 -SkipGo 的 setup。' -ForegroundColor Yellow
  }
  else {
    # 灰流丽的卡牌 ID：既验证 CLI，也会触发首次数据库 clone（约 120 MB）。
    & $exe get-card-by-id 14558128 --format json | Out-Null
    if ($LASTEXITCODE -ne 0) {
      Write-Host '数据库准备失败，请检查网络/代理后重试。' -ForegroundColor Red
      exit 1
    }
    Ok "数据库已就绪：$env:LOCALAPPDATA\ygo-db"
  }
}

Write-Host ''
Write-Host '环境准备完成。运行 .\scripts\verify.ps1 做一次完整验证。' -ForegroundColor Green
