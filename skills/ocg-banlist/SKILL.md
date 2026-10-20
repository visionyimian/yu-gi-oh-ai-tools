---
name: ocg-banlist
description: 获取 YGOCore 的 OCG / TCG 禁限卡表，并校验一副 .ydk 是否超限。当需要确认某张卡在当前环境的限制张数、分析卡组前要确认构筑合法性、或用户问「这套牌能打吗 / 有没有禁卡」时使用。触发词：禁卡表、限制卡、准限制、限卡、这套牌合法吗、能不能带 3 张。
---

# ocg-banlist

## 职责

- ✅ 拉取最新的 OCG / TCG 禁限卡表
- ✅ 输出结构化列表（JSON / CSV）供后续步骤使用
- ✅ 校验一副 `.ydk` 是否超过限制
- ❌ 不判断卡组强弱（那是 `deck-analyzer` 的事）
- ❌ 不校验卡组张数是否 40–60（那是 `count-deck` 的事）

## 为什么需要单独一个 skill

`cards.cdb` 里**没有**禁限数据：`datas` 表只有 id/ot/alias/setcode/type/atk/def/level/race/attribute/category 这些字段。上游 `mycard/ygopro-database` 甚至把 `lflist.conf` 写进了 `.gitignore`，刻意不随卡库发布。

所以整套分析链路对「这套牌是否合法」原本是盲的，必须单独获取。

## 数据源

YGOCore 客户端使用的 `lflist.conf`，一个文件里并列了历年的 OCG 与 TCG 列表：

```text
#[2026.10][2026.9 TCG][2026.7]...     ← 注释，列出所有可用列表
!2026.10                               ← 列表名
#forbidden
68059897 0 --M∀LICE＜Q＞RED RANSOM
#limit
32061192 1 --M∀LICE＜P＞Dormouse
#semi limit
14558127 2 --灰流うらら
```

默认从两个镜像依次尝试：

1. `https://raw.githubusercontent.com/Fluorohydride/ygopro/master/lflist.conf`
2. `https://raw.githubusercontent.com/mycard/ygopro/master/lflist.conf`

## 用法

```bash
# 最新 OCG 列表的摘要（默认）
python skills/ocg-banlist/scripts/fetch_banlist.py

# 最新 TCG 列表
python skills/ocg-banlist/scripts/fetch_banlist.py --tcg

# 指定某一期
python skills/ocg-banlist/scripts/fetch_banlist.py --list 2026.7

# 落成 JSON / CSV，供后续步骤读取
python skills/ocg-banlist/scripts/fetch_banlist.py --format json -o ocg_limit.json

# 校验一副牌（超限时退出码为 1）
python skills/ocg-banlist/scripts/fetch_banlist.py --check deck.ydk

# 离线：用本地文件
python skills/ocg-banlist/scripts/fetch_banlist.py --file ./lflist.conf
```

| 参数 | 说明 |
|---|---|
| `--list NAME` | 精确选择列表，例如 `2026.10`、`2026.9 TCG` |
| `--tcg` | 选择文件里最新的 TCG 列表；默认选最新的 OCG 列表 |
| `--format` | `text`（默认）/ `json` / `csv` |
| `-o PATH` | 写入文件，默认打印到标准输出 |
| `--check YDK` | 校验该 `.ydk`，输出每一处超限 |
| `--file PATH` | 用本地 `lflist.conf`，不联网 |
| `--url URL` | 覆盖下载地址，可重复 |

## 判定规则

| 限制数 | 含义 | 允许张数 |
|---|---|---|
| `0` | 禁止 | 0 |
| `1` | 限制 | 1 |
| `2` | 准限制 | 2 |
| 未出现 | 无限制 | 3 |

- 真正的依据是每行的**第二个字段**，`#forbidden` / `#limit` / `#semi limit` 只是分段注释
- **passcode 在文件里带前导零**（如 `08903700`），而 `.ydk` 里没有，比较前统一转成整数
- 卡名只是注释，可能被改动，判断时不要依赖它

## 输出

`--format json` 的结构：

```json
{
  "list": "2026.10",
  "format": "ocg",
  "source": "https://raw.githubusercontent.com/...",
  "cards": [{ "passcode": 32061192, "limit": 1, "name": "M∀LICE＜P＞Dormouse" }]
}
```

`--check` 的输出（有违规时退出码为 1）：

```text
deck.ydk：43 张，对照列表 2026.10
违规 1 处：
  [超限] 69272449  带 3 张，限制 1  Maliss <P> White Rabbit
```

## 注意事项

- **必须显式区分 OCG / TCG**：同一个文件里两套列表并列，同一张卡可能一边禁止一边无限制。默认取 OCG，用 `--tcg` 切到 TCG。
- **社区维护，不是 Konami 官方**：官方公告后通常几天内跟进，存在滞后窗口；存疑时以官方公告为准。
- **卡名是日文/英文**（lflist 的注释），要中文卡名请用 `ygo-db-cli get-card-by-id` 反查。
- 建议把 `--format json` 的结果随分析产物一起存放，方便复现「当时用的是哪一期列表」。
