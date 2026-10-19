#!/usr/bin/env pwsh
<#
.SYNOPSIS
  验证 yu-gi-oh-ai-tools 在这台机器上确实能跑。

.DESCRIPTION
  依次执行：
    1. Go 单元测试            go test ./...
    2. Python 单元测试        pytest
    3. ruff 检查              skills/（既有告警默认不阻断）
    4. CLI 冒烟测试           按 ID / 按 YDK 查询卡牌
    5. Skill 脚本冒烟测试     count_deck.py、starter_probability.py、calculate.py
  任何一步失败都会以非 0 退出码结束。

.PARAMETER StrictLint
  把 ruff 告警也当作失败条件。
#>
[CmdletBinding()]
param(
  [switch]$StrictLint
)

# 原生命令会往 stderr 写进度，不能让它们直接终止脚本；失败由退出码判定。
$ErrorActionPreference = 'Continue'
$repo = Split-Path -Parent $PSScriptRoot
$failed = New-Object System.Collections.ArrayList

function Step($message) { Write-Host ""; Write-Host "==> $message" -ForegroundColor Cyan }
function Ok($message) { Write-Host "    [PASS] $message" -ForegroundColor Green }
function Fail($message) {
  Write-Host "    [FAIL] $message" -ForegroundColor Red
  [void]$script:failed.Add($message)
}

# ------------------------------------------------------------- Go 单元测试 ---
Step 'Go 单元测试 (ygo-db)'
Push-Location (Join-Path $repo 'ygo-db')
try {
  $env:GOTOOLCHAIN = 'auto'
  go test ./... 2>&1 | ForEach-Object { Write-Host "    $_" }
  if ($LASTEXITCODE -eq 0) { Ok 'go test ./...' } else { Fail "go test 退出码 $LASTEXITCODE" }
}
finally { Pop-Location }

# --------------------------------------------------------- Python 单元测试 ---
$venvPy = Join-Path $repo 'skills\.venv\Scripts\python.exe'
Step 'Python 单元测试 (skills)'
if (-not (Test-Path $venvPy)) {
  Fail '缺少 skills/.venv，先运行 .\scripts\setup.ps1'
}
else {
  Push-Location (Join-Path $repo 'skills')
  try {
    & $venvPy -m pytest -q 2>&1 | ForEach-Object { Write-Host "    $_" }
    if ($LASTEXITCODE -eq 0) { Ok 'pytest' } else { Fail "pytest 退出码 $LASTEXITCODE" }

    Step 'ruff 检查 (skills)'
    & '.\.venv\Scripts\ruff.exe' check . 2>&1 | Select-Object -Last 3 | ForEach-Object { Write-Host "    $_" }
    if ($LASTEXITCODE -ne 0) {
      if ($StrictLint) { Fail "ruff 退出码 $LASTEXITCODE" }
      else { Write-Host '    [WARN] ruff 有既有告警，未阻断（加 -StrictLint 可改为失败）' -ForegroundColor Yellow }
    }
    else { Ok 'ruff check' }
  }
  finally { Pop-Location }
}

# ------------------------------------------------------------- CLI 冒烟测试 ---
Step 'CLI 冒烟测试'
$exe = Join-Path $repo 'ygo-db\bin\ygo-db-cli.exe'
if (-not (Test-Path $exe)) {
  Fail '缺少 ygo-db/bin/ygo-db-cli.exe，先运行 .\scripts\setup.ps1'
}
else {
  $json = & $exe get-card-by-id 14558128 --format json 2>$null
  if ($LASTEXITCODE -eq 0 -and ($json -join '') -match '灰流丽') { Ok 'get-card-by-id (zh-CN)' }
  else { Fail 'get-card-by-id (zh-CN)' }

  $json = & $exe get-card-by-id 14558128 --format json --lang en-US 2>$null
  if ($LASTEXITCODE -eq 0 -and ($json -join '') -match 'Ash Blossom') { Ok 'get-card-by-id (en-US)' }
  else { Fail 'get-card-by-id (en-US)' }

  $tmp = Join-Path $env:TEMP ("ygo-verify-{0}.csv" -f [guid]::NewGuid())
  try {
    & $exe get-cards-by-ydk -i (Join-Path $repo 'test-dir-zh-cn\test-deck.ydk') -o $tmp 2>$null
    $code = $LASTEXITCODE
    $lines = 0
    if (Test-Path $tmp) { $lines = (Get-Content $tmp -Encoding UTF8 | Measure-Object -Line).Lines }
    if ($code -eq 0 -and $lines -gt 100) { Ok "get-cards-by-ydk（导出 $lines 行 CSV）" }
    else { Fail 'get-cards-by-ydk' }
  }
  finally { Remove-Item $tmp -ErrorAction SilentlyContinue }
}

# ---------------------------------------------------------- Skill 脚本冒烟 ---
Step 'Skill 脚本冒烟测试'
if (Test-Path $venvPy) {
  Push-Location (Join-Path $repo 'skills')
  try {
    $out = & $venvPy 'count-deck\scripts\count_deck.py' (Join-Path $repo 'test-dir-zh-cn\test-deck.ydk') 2>&1
    if ($LASTEXITCODE -eq 0 -and ($out -join ' ') -match 'main:') { Ok ('count_deck.py -> ' + ($out -join ' / ')) }
    else { Fail 'count_deck.py' }

    $out = & $venvPy 'starter-probability\scripts\starter_probability.py' -d 40 -t 3 2>&1
    if ($LASTEXITCODE -eq 0 -and ($out -join ' ') -match 'at_least_1') { Ok 'starter_probability.py' }
    else { Fail 'starter_probability.py' }

    $out = & $venvPy 'simple-calculator\scripts\calculate.py' '1+2*3' 2>&1
    if ($LASTEXITCODE -eq 0 -and ($out -join '').Trim() -eq '7') { Ok 'calculate.py -> 7' }
    else { Fail 'calculate.py' }
  }
  finally { Pop-Location }
}

# -------------------------------------------------------------------- 汇总 ---
Write-Host ''
if ($failed.Count -eq 0) {
  Write-Host '全部验证通过，项目可以在这台机器上运行。' -ForegroundColor Green
  exit 0
}
Write-Host "有 $($failed.Count) 项失败：" -ForegroundColor Red
$failed | ForEach-Object { Write-Host "  - $_" -ForegroundColor Red }
exit 1
