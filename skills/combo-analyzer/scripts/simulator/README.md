# simulator/

用 ygopro-core 验证做场线是否**真的能执行**。目前只有不需要引擎的部分。

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
| M0 | 编译出 `ocgcore.dll` | ✅ **完成**（1444 KB，`OCG_GetVersion` → 11.0，10 个函数全部导出）|
| M1 | `OCG_CreateDuel` 成功（ctypes 结构体对齐） | ⬜ |
| M2 | `OCG_DuelNewCard` 装完 55 张卡 | ⬜ |
| M3 | 卡脚本能加载（`constant.lua` + `utility.lua` + `c<code>.lua`） | ⬜ |
| M4 | 解析 `MSG_SELECT_IDLECMD` / `MSG_SELECT_CHAIN` 并能回应 | ⬜ |
| M5 | 按 24 步剧本驱动，走完全程 | ⬜ |

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

编译选项照着 `premake5.lua` 抄：C++17、`/MT` 静态运行库、`WIN32/_WIN32/NOMINMAX`、
共享库加 `OCGCORE_EXPORT_FUNCTIONS`；Lua 的 `.c` 文件要**按 C++ 编译**（`/TP`）并强制
包含 `luaconf-customize.h`。

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

## 接引擎时的顺序

1. 编译（`premake5 gmake2` 或 `scripts/generate.bat`），产出 `ocgcore.dll`
2. `ocgcore.py`：ctypes 绑定 `ocgapi.h` 的 10 个函数 + `OCG_DuelOptions` 对齐
3. `callbacks.py`：cardReader 查 `cards.cdb`、scriptReader 读 `.cache/ygopro-scripts`
4. `messages.py`：按 `ocgapi_constants.h` 的 opcode 解析二进制流
5. `executor.py`：把 `combo_lines` 的步骤翻译成选项匹配
6. `simulate.py`：CLI，输出 `simulation_result.json`

**注意**：引擎是 AGPL-3.0，本地分析自用无碍，要分发需考虑开源义务。
