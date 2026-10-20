# 在 Windows 本机运行

本机（`D:\dsharness-work\ygo-zjzheng-ai\yu-gi-oh-ai-tools`）已完成环境搭建并验证通过。
下面是我们实际使用的步骤，换机器时照做即可。

## 一键命令

在本目录打开 PowerShell，执行：

```powershell
# 1) 装环境：编译 CLI + 建 Python 虚拟环境 + 拉卡牌数据库
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup.ps1

# 2) 验证：跑全部测试 + 冒烟运行
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify.ps1
```

`verify.ps1` 的最后一行是 `全部验证通过，项目可以在这台机器上运行。`，退出码为 `0`。

> 提示：`-ExecutionPolicy Bypass` 只是让本次脚本可以执行，不会改系统策略。
> 本机没有 PowerShell 7（`pwsh`），所以上面的命令用系统自带的 `powershell`（5.1）。

## 本机环境现状

| 组件 | 版本 | 说明 |
|---|---|---|
| Go | 1.21.4（已装） | `go.mod` 要求 **1.26.1**；`GOTOOLCHAIN=auto` 已自动下载 1.26.1 工具链，无需手动升级 |
| Python | 3.15.0 | 满足 `requires-python >= 3.14` |
| git | 2.37.0 | CLI 首次运行要 clone 卡牌数据库 |
| uv / just | 未安装 | **不需要**；CI 用 uv，本地用 venv + pip 等价替代 |

生成/缓存的东西：

| 路径 | 内容 |
|---|---|
| `ygo-db\bin\ygo-db-cli.exe` | 编译好的 CLI（约 12 MB，已在 `.gitignore` 中） |
| `skills\.venv\` | Python 虚拟环境（pytest、ruff） |
| `%LOCALAPPDATA%\ygo-db\` | 卡牌数据库 clone，约 **118 MB**，首次运行自动下载 |
| `skills\.pytest_cache`、`skills\.ruff_cache` | 测试/检查缓存 |

## 手动步骤（等价于 setup.ps1）

```powershell
# Go CLI
cd ygo-db
$env:GOTOOLCHAIN = 'auto'          # 允许自动下载 go1.26.1
go build -o bin\ygo-db-cli.exe ./cmd/ygo-db-cli

# Python
cd ..\skills
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install "pytest>=9.0.2" ruff
```

## 已经验证过什么

```
go test ./...                   5 个包全部 ok（cdb / git / ydk / cli）
pytest                          114 passed（离线用例；test_fetch_meta_deck 需要联网）
ruff check .                    All checks passed
ruff format . --check           全部已格式化
ygo-db-cli get-card-by-id       中文库、英文库（--lang en-US）均正常
ygo-db-cli get-cards-by-ydk     示例卡组导出 145 行 CSV
count_deck.py / starter_probability.py / calculate.py   正常
```

ruff 原先有 11 条既有告警（`I001` 导入排序、`BLE001` 宽泛 `except` 等），已在本仓库修掉，
`verify.ps1` 的 `-StrictLint` 现在可以作为失败条件使用。

## 网络与代理

若干脚本需要联网：`fetch_banlist.py`（拉 `lflist.conf`）、`script_facts.py`（拉卡脚本）、
以及 `ygo-db-cli` 首次运行的卡库 clone。它们都用标准库 `urllib`，遵循 `HTTP_PROXY` / `HTTPS_PROXY`。

**IPv6-only 代理的坑**：如果代理客户端只监听 `::`（FlClash 常见），把代理写成 `localhost`
可能被 Python 解析到 IPv4 而连接被拒；改用显式 IPv6 字面量：

```powershell
$env:HTTP_PROXY  = "http://[::1]:7890"
$env:HTTPS_PROXY = "http://[::1]:7890"
```

git 读的是 `git config http.proxy`，**不受**上面两个变量影响，需要单独设置或用
`git -c http.proxy=... push` 临时覆盖。


## 怎么用

### 1. 查卡 / 导出卡组数据

```powershell
$cli = '.\ygo-db\bin\ygo-db-cli.exe'

& $cli get-card-by-id 14558128 --format json          # 灰流丽
& $cli get-cards-by-name '灰流丽' --format json
& $cli get-cards-by-archetypes '闪刀' --format json
& $cli get-cards-by-ydk -i .\test-dir-zh-cn\test-deck.ydk -o deck_raw.csv
& $cli get-card-by-id 14558128 --lang en-US --format json   # 英文卡名
```

`get-cards-by-ydk` 的 `--format` 支持 `csv`（默认，给分析用）、`json`、`yaml`。

想让 Skill 里那种裸命令 `ygo-db-cli ...` 也能用，把 `bin` 加进当前会话的 PATH：

```powershell
$env:PATH = "$PWD\ygo-db\bin;$env:PATH"
ygo-db-cli get-card-by-id 14558128
```

### 2. 卡组分析流水线

`skills/ygo-deck-analyze`、`deck-parser`、`deck-analyzer` 是**给 AI 助手读的提示词型 Skill**
（`SKILL.md`），主体不是可执行程序，需要用 Gemini CLI / Claude Code / 本类 AI 环境加载。
但其中的机械部分（找二卡动点、穷举起手）已经脚本化，可以单独跑：

```
test-deck.ydk
  → [CLI]  ygo-db-cli get-cards-by-ydk        → deck_raw.csv / deck_raw.json
  → [脚本] deck-parser/scripts/combo_scan.py  → combo_candidates.json（需求 → 满足者）
  → [AI]   确认动点，写 combos.json
  → [脚本] deck-parser/scripts/hand_matrix.py → 能动率 / 死手率
  → [AI]   deck-parser / deck-analyzer        → deck_parsed.json / deck_analysis.json
  → [AI]   ygo-deck-analyze                   → report.md
```

手动跑一遍机械部分：

```powershell
$cli = '.\ygo-db\bin\ygo-db-cli.exe'
$py  = '.\skills\.venv\Scripts\python.exe'

& $cli get-cards-by-ydk -i deck.ydk --format json -o deck_raw.json
& $py skills\deck-parser\scripts\combo_scan.py deck_raw.json -o combo_candidates.json
& $py skills\deck-parser\scripts\hand_matrix.py deck_raw.json combos.json
```

`combo_scan.py` 会列出每只 Link 的素材门槛、每张卡的外部触发条件，以及「谁的需求能被谁满足」。
`hand_matrix.py` 用 `combos.json` 里的动点规则穷举全部 C(40,5)=658008 种起手，
输出单卡动 / 二卡动 / 死手的真实比例；死手率超过 15% 会告警，提示你可能漏了启动点。

`test-dir-zh-cn\test-deck_analysis\` 里有一份完整的历史产物可以直接对照。

### 3. 纯计算脚本（不依赖 AI）

```powershell
$py = '.\skills\.venv\Scripts\python.exe'

& $py skills\count-deck\scripts\count_deck.py .\test-dir-zh-cn\test-deck.ydk
# main: 43 / extra: 15 / side: 15

& $py skills\starter-probability\scripts\starter_probability.py -d 43 -t 3
# at_least_1: 31.64% ...

& $py skills\simple-calculator\scripts\calculate.py "1+2*3"
```

## 常见问题

**首次运行 CLI 很慢 / 卡住**
第一次会 `git clone https://github.com/mycard/ygopro-database.git`，约 118 MB。
网络受限时先设代理再跑：`$env:HTTPS_PROXY='http://127.0.0.1:7890'`。
数据库更新失败时 CLI 会打印 warning 并继续用本地已有数据，不会中断。

**`go: downloading go1.26.1` 失败**
说明拿不到 Go 工具链。可手动安装 Go 1.26.1 后重试，或设置国内镜像：
`$env:GOPROXY='https://goproxy.cn,direct'`。

**脚本报「禁止运行脚本」**
就是 `ExecutionPolicy` 限制，用上面带 `-ExecutionPolicy Bypass` 的命令即可。

**`python` 指向别的版本**
`setup.ps1` 会检查版本，低于 3.14 直接报错退出；用 `py -3.15` 或改 `PATH` 调整。
