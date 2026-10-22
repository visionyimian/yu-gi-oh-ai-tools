# simulator/

用 ygopro-core 验证做场线是否**真的能执行**。

现在能跑完一条完整的二卡动线：**睡鼠＋白兔 → 小男巫 → 连接解码员 → 备份员**，11 步，
移动日志与录像 `10-17「22：03：56」` 逐条对得上，全程引擎日志 0 条报错。

## 为什么要它

`combo_lines` 里的 `verified: false` 表示「按卡面推导，没跑过」。这是诚实的，
但不等于正确——账簿能自洽，步骤仍可能在某一步被规则拒绝。

引擎能做到而推导做不到的事：

| 现在 | 接了引擎之后 |
|---|---|
| 读卡面判断「这步能不能发动」 | 引擎拒绝就拒绝 |
| 推演终场是什么 | `OCG_DuelQueryLocation` 查实际场面 |
| 数牌算能动率（上界） | 跑 N 手，算执行率 |

## 进度

| 关卡 | 内容 | 状态 |
|---|---|---|
| M0 | 编译出 `ocgcore.dll` | ✅ **完成**（1444 KB，`OCG_GetVersion` → 11.0）|
| M1 | `OCG_CreateDuel` 成功 | ✅ **完成**（`SUCCESS`，结构体对齐正确）|
| M2 | `OCG_DuelNewCard` 装完卡组 | ✅ **完成**（55 张：主 40 / 额外 15）|
| M3 | 卡脚本能加载 | ✅ **完成**（3 个全局脚本 + 兼容层 + 40 个卡脚本）|
| M4 | 解析消息流 | ✅ **完成**（`MSG_DRAW player=0 抽 5 张`）|
| **M5a** | 通召白兔 | ✅ **完成**（`seed=8`，引擎接受动作并回了 `MSG_SUMMONED`）|
| **M5b** | 连锁窗口里发动白兔① | ✅ **完成**（`SELECT_EFFECTYN` → `CHAIN_SOLVING` → 选陷阱 → `MSG_SET`）|
| **M5c** | 发动 TB-11（主阶段动作）| ✅ **完成**（`SELECT_IDLECMD.activate` → cost 选卡 → `SPSUMMONED`）|
| **M5d** | 剧本匹配器走完 11 步 | ✅ **完成**（10 个种子里 9 个 11/11）|

```
$ python m5d.py --line 睡鼠 --seed 27
   1. ✓ 通常召唤「码丽丝<兵卒>睡鼠」
   2. ✓ 睡鼠①：从卡组把「柴郡猫」除外
   3. ✓ 柴郡猫③：支付 300 基本分回到场上
   4. ✓ 柴郡猫①：除外手卡的「白兔」
   5. ✓ 白兔③：支付 300 基本分回到场上
   6. ✓ 白兔①：从卡组盖放「码丽丝<代码>TB-11」
   7. ✓ 睡鼠＋白兔连接召唤「电子界小男巫」
   8. ✓ 柴郡猫 → 「连接解码员」
   9. ✓ 小男巫③：除外墓地柴郡猫，检索电子界调整
  10. ✓ 备份员①：以连接解码员为条件从手卡自跳
  11. ✓ 备份员②：检索码丽丝并弃 1 张
[M5d] 通过：11 步全部执行完
```

每一步都要求**看到证据**才算过：`MSG_SUMMONING/SPSUMMONING/CHAINING/MOVE` 里出现这一步
的卡号。没看到就报「第 N 步没有真的发生」——因为引擎会安静地丢弃不合法的动作，
光看「我发了包、它没报错」等于没验证。

## M5d 踩到的坑

**10. 规则 flags 必须给 MR5。** `OCG_DuelOptions.flags = 0` 等于「没有额外怪兽区」，
朝下的箭头全部落空：小男巫（↓↘）站在主要怪兽区什么都指不到，连接端特召成功也
不触发它的③。给 `DUEL_MODE_MR5`（`0x2e800`）之后，额外怪兽区出现，箭头才落进
主要怪兽区。录像头里的 `masterRule` 是 6（MDPro3 的 MR5），对得上。

**11. 连接标记在 `datas.def` 列，不在 `link_marker` 列。** 这版 `cards.cdb` 没有
`link_marker`，连接怪兽的箭头存在 `def` 里（同时 `level` 存连接数值）。
漏填的后果不是报错，而是**连接召唤永远不出现在 `MSG_SELECT_IDLECMD` 的 spsummon 段**——
引擎认为没有任何区域能放下这只怪兽。见 `probe._link_marker()`。

**12. 卡脚本比引擎新：14 个函数根本不存在。** `Card.IsLinkType` / `Card.IsLinkRace` /
`Card.IsLinkSetCard` / `Card.IsAllTypes` / `Card.IsFaceupEx` / `Duel.GetMustMaterial` 这些
在 `mycard/ygopro-scripts` 的卡脚本里被当引擎 API 用，但 edo9300 版 `ocgcore` 的
`libcard.cpp` / `libduel.cpp` 里没有，`constant/utility/procedure` 也没定义。

危害最大的一个是 **`Duel.GetMustMaterial`**：它在 `Auxiliary.LinkCondition` 里，
也就是**每一次**连接召唤判定都要过。缺了它，素材过滤抛 lua 错，引擎把这次召唤判定为
不可用——现象是「场上素材够了，就是不给连接召唤」。

`ocgcompat.lua` 补上这些函数（每段都有 `if X==nil` 守卫，换成自带这些 API 的核心时
不会覆盖任何东西）；`audit_scripts.py` 可以一次列出所有这类缺口：

```bash
python audit_scripts.py --core ../../../../vendor/ygopro-core-src --scripts .cache/ygopro-scripts
```

> 只补函数名不够判断语义时，以卡脚本的用法为准：`Card.IsLinkType` 被用作素材过滤
> （`AddLinkProcedure(c, FilterBoolFunction(Card.IsLinkType, TYPE_EFFECT), 2)`），
> 而访问码语者的素材是「效果怪兽 2 只以上」——所以它必须等于 `IsType`，
> 不能额外要求「是连接怪兽」。

**13. 连接素材走 `MSG_SELECT_UNSELECT_CARD`，不是 `MSG_SELECT_CARD`。** 素材是一张一张
点的，每次引擎都重算一遍是否已经满足条件。

```
uint8 player, uint8 finishable, uint8 cancelable, uint32 min, uint32 max,
uint32 nselect, nselect × (code + loc_info),      ← 还没选的候选
uint32 nunselect, nunselect × (code + loc_info)   ← 已选中、还可以退的
```

回应的**第一个** `int32` 是「1 = 我选了下面那张 / -1 = 结束或取消」，第二个才是下标：
`int32 1 + int32 index`。回 `-1` 等于取消这次召唤——引擎不会报错，只会什么都不做，
于是上一步看起来「成功了」。

**14. 放哪一格决定效果能不能接上。** 小男巫站 5 号（左额外怪兽区）时 ↓ 指 1 号、
↘ 指 2 号；站 0 号主要怪兽区时 ↓ 指魔陷区、↘ 指魔陷区，等于什么都没指。
一律「放最左边的空格」会让 `柴郡猫 → 连接解码员` 这步之后接不上小男巫③。
`field_model.py` 复刻了 `card::get_linked_zone` 的算法，放牌时优先选**被自己连接怪兽指着**
的格子，其次额外怪兽区。

**15. 起动效果（手卡自跳）在 idle 的 `activate` 段。** 备份员① 不是连接召唤、也不是
额外卡组召唤，`spsummon` 段里没有它；`special_summon` 这类步骤要查 `activate` 段。

## M5b 踩到的坑

**6. `setcodes` 不给，效果会「静默消失」。** 白兔① 的 target 用 `s.setfilter` 判断卡组里
有没有码丽丝陷阱，而 `Card.IsSetCard` 依赖 cardReader 填的 `setcodes`。填成 NULL 时：

- 引擎不报错、Lua 不报错
- 连锁窗口里**根本不会出现这张卡的效果**

cdb 的 `setcode` 是整数（码丽丝是 `447` = 0x1BF），要拆成最多 4 个 uint16、
以 0 结尾传给引擎。

**7. 诱发效果走 `MSG_SELECT_EFFECTYN`，不是 `MSG_SELECT_CHAIN`。**
「要不要发动这个效果」是单独一条消息：

```
uint8 player, uint32 code, loc_info(10), uint64 description
```

回应是 int32 的 0/1。它后面才接 `MSG_CHAINING`/`MSG_CHAINED`。

**8. `MSG_SELECT_CARD` 的回应是「类型 + 个数 + 下标」。**

```
int32  type     0 = uint32 下标，1 = uint16，2 = uint8，3 = 位图，-1 = 取消
uint32 count
uint32 index × count
```

选卡列表里的 `index` 是**排序后**的位置，不是 `sequence`。

**9. 盖放魔陷会再问一次 `MSG_SELECT_PLACE`**，这次可用区在 `flag` 的 bit 8~12
（序号 8~12 对应魔陷区 1~5），回应里的 `sequence` 要减 8。

## M5a 踩到的坑

**4. 引擎自己「不洗牌」。** `Startup` 处理器直接从 `main.back()` 抽，顺序就是
`OCG_DuelNewCard` 的插入顺序（`seq` 越大越先抽到）。洗牌是**客户端**职责——
用 `random.Random(seed).shuffle(main)` 自己做，种子固定即可复现。

症状：双方抽到一模一样的 5 张，而且正好是主卡组末尾那 5 张。

**5. `MSG_SELECT_PLACE` 的 `flag` 是「禁用掩码」。** 置位表示**不可用**：

```
uint8  player
uint8  count
uint32 flag     0xffffffe0 → 0~4 号怪兽区可用（低 5 位是 0）
```

回应是每个选择 3 字节 `(player, location, sequence)`。按「置位=可用」解析会选到
被禁用的格子，然后无限收到 `MSG_RETRY`。

## M1~M4 踩到的坑

按顺序记下来，省得再接一次：

**1. 全局脚本有三个，必须自己加载，顺序不能颠倒。**

```
constant.lua    →  所有常量（POS_*, TYPE_*, EFFECT_*）
utility.lua     →  GetID(), aux.FilterBoolFunction 等
procedure.lua   →  aux.AddLinkProcedure 等「过程」辅助
```

引擎**不会**通过 `scriptReader` 索要它们；要自己 `OCG_LoadScript(duel, ...)`，
而且必须在 `OCG_DuelNewCard` 之前。少一个的症状：

| 少加载 | 症状 |
|---|---|
| `utility.lua` | 每个卡脚本报 `attempt to call a nil value (global 'GetID')` |
| `procedure.lua` | 所有连接怪兽报 `attempt to call a nil value (field 'AddLinkProcedure')` |
| `constant.lua` | 常量全为 nil，效果条件判断全错 |

**2. 消息类型是 `uint8`，不是 `uint32`。**

```
uint32 size      整条消息字节数（含 1 字节类型）
uint8  type      MSG_*
...              payload
```

读成 4 字节会把 payload 前 3 字节吞掉，后面全错位，且引擎不报错——只会等你回应一个
它不认识的包然后卡住。见 `messages.py` 的 `split()`。

**3. `c0.lua` 缺失不致命。** 引擎给「没有脚本的卡」（如通常怪兽）要占位脚本，
返回 0 就行，只是日志会吵。


**已完成（不需要引擎）**：

- ✅ `gen_constants.py` / `ocg_constants.py` —— 374 个常量，11 个分组

## 怎么编译（M0）

不需要 premake5。`premake5.lua` 已经把源文件和编译选项列全了，`build_ocgcore.bat`
把它们翻译成直接的 `cl` / `lib` / `link` 调用。

```bat
build_ocgcore.bat <源码目录> <输出目录>
build_ocgcore.bat D:\vendor\ygopro-core-src D:\vendor\build
```

前置条件：

1. **Visual Studio 带 C++ 工具链**（`vswhere -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64` 能查到）。
   脚本自己用 `vswhere` 找 `vcvars64.bat`，不写死路径。
2. **Lua 源码**放在 `<源码目录>\lua\src`。用 [lua/lua](https://github.com/lua/lua) 的
   **v5.4.7** tag（`interpreter.cpp` 里有 `#if LUA_VERSION_NUM <= 503` 分支，5.3/5.4 都支持；
   5.5 不要用）。
3. ygopro-core 源码从 `codeload.github.com/edo9300/ygopro-core/zip/refs/heads/master` 下载解压
   （zip 不含子模块，所以 lua 要单独下）。

> 卡脚本取自 `mycard/ygopro-scripts`，和 edo9300 版核心有 14 个 API 落差（见坑 12），
> 靠 `ocgcompat.lua` 兜住。mycard 自己也有核心（`mycard/ygopro-core`），那几个函数
> 它一个不缺，但它用的是**更老的 C API**（`create_duel` / `process` / `get_message`，
> 而不是 `OCG_*` 那套），要用就得在 `ocgcore.py` 里再写一套绑定。
> 想彻底避开兼容层的话，这是唯一的路。

编译选项照着 `premake5.lua` 抄：C++17、`/MT` 静态运行库、`WIN32/_WIN32/NOMINMAX`、
共享库加 `OCGCORE_EXPORT_FUNCTIONS`；Lua 的 `.c` 文件要**按 C++ 编译**（`/TP`）并强制
包含 `luaconf-customize.h`。Lua 标准库里 `lutf8lib` **不能跳过**（mycard 版核心的
`interpreter` 会显式调 `luaopen_utf8`），`linit` 反而可以跳过——解释器自己接管了。

> `.bat` 文件必须**纯 ASCII**——cmd 按 OEM 代码页解析，中文注释会乱码到解析失败。

## `gen_constants.py`

从 [`edo9300/ygopro-core`](https://github.com/edo9300/ygopro-core) 的
`ocgapi_constants.h` 生成 Python 常量表。

```bash
python gen_constants.py                      # 下载并生成 ocg_constants.py
python gen_constants.py --file header.h      # 用本地副本
python gen_constants.py --check              # 只统计，不写文件
```

产物 `ocg_constants.py` 里每一组都有两样东西：

```python
MSG_SELECT_IDLECMD = 0xb          # 正向：名字 → 值
MESSAGES = {0xb: 'MSG_SELECT_IDLECMD', ...}   # 反向：值 → 名字

describe(0x0C, LOCATIONS)   # → 'LOCATION_MZONE|LOCATION_SZONE (LOCATION_ONFIELD)'
```

为什么要这份表：`cards.cdb` 的 `type` 位掩码、`QUERY_*` 标志、区域掩码全是数字，
引擎只吐数字。有了反向表，调试时看到 `loc=0x0A` 能立刻翻成
`LOCATION_HAND|LOCATION_SZONE`，不用每次翻头文件。

上游更新时重跑一次即可；`skills/tests/test_ocg_constants.py` 会校验
`MSG_SELECT_IDLECMD` 等 13 个关键值没变。

## 分析产物从哪来

模拟器要读 `deck_analysis.json`，但它不在 `main` 上（生成物，不进主分支）。
取回：

`ash
python fetch_analysis.py --list                        # 看分支上有哪些卡组
python fetch_analysis.py --deck 奥艺码丽丝              # 默认取到 ./奥艺码丽丝_analysis
python fetch_analysis.py --deck 奥艺码丽丝 --out ../decks/奥艺码丽丝_analysis
`

它用 `git show <rev>:<path>` 取 blob 的原始字节，不经过 PowerShell 的编码转换
（否则中文 JSON 会被加 BOM 或改成 CRLF，`json.load` 直接报错）。

## 接引擎时的顺序

1. 编译（`premake5 gmake2` 或 `scripts/generate.bat`），产出 `ocgcore.dll`
2. `ocgcore.py`：ctypes 绑定 `ocgapi.h` 的 10 个函数 + `OCG_DuelOptions` 对齐
3. `callbacks.py`：cardReader 查 `cards.cdb`、scriptReader 读 `.cache/ygopro-scripts`
4. `messages.py`：按 `ocgapi_constants.h` 的 opcode 解析二进制流
5. `executor.py`：把 `combo_lines` 的步骤翻译成选项匹配
6. `simulate.py`：CLI，输出 `simulation_result.json`

**注意**：引擎是 AGPL-3.0，本地分析自用无碍，要分发需考虑开源义务。
