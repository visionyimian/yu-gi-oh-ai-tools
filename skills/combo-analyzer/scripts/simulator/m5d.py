#!/usr/bin/env python3
"""M5d：按 combo_lines 的剧本驱动引擎，逐步验证每一步能不能执行。

前三个里程碑（m5a/m5b/m5c）各自硬编码了一两个动作。这里把它们收成一个通用执行器：

- 每一步读 `action` 和 `uses`，决定去**哪个消息**里找选项
  - `normal_summon` → `SELECT_IDLECMD.summon` 里找卡号
  - `link_summon`   → `SELECT_IDLECMD.spsummon`（额外卡组的怪兽从这里出来）
  - `activate` / `special_summon` → 依次试 `SELECT_EFFECTYN` / `SELECT_CHAIN` / `IDLECMD.activate`
- 找不到就**停在步骤 N**，把当时引擎给的全部选项打出来——这是最有用的诊断信息
- 与当前步骤无关的消息用「安全默认值」回应（放弃连锁 / 不进战阶），保证引擎不会卡死

用法::

    python m5d.py --dll build/ocgcore.dll --cdb cards.cdb --ydk deck.ydk \\
        --scripts scripts/ --analysis deck_analysis.json
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import struct
from pathlib import Path

import messages as msg
from field_model import Field
from m5a import Session
from ocg_constants import (
  LOCATION_MZONE,
  LOCATION_SZONE,
  MSG_CHAINING,
  MSG_LPUPDATE,
  MSG_MOVE,
  MSG_PAY_LPCOST,
  MSG_SELECT_CARD,
  MSG_SELECT_CHAIN,
  MSG_SELECT_EFFECTYN,
  MSG_SELECT_IDLECMD,
  MSG_SELECT_OPTION,
  MSG_SELECT_PLACE,
  MSG_SELECT_POSITION,
  MSG_SELECT_UNSELECT_CARD,
  MSG_SELECT_YESNO,
  MSG_SPSUMMONED,
  MSG_SPSUMMONING,
  MSG_SUMMONED,
  MSG_SUMMONING,
  TYPE_LINK,
)

# 能证明「刚才那个动作真的发生了」的消息：召唤/特殊召唤/发动
SUMMON_EVIDENCE = (MSG_SUMMONING, MSG_SUMMONED, MSG_SPSUMMONING, MSG_SPSUMMONED)


class Deck:
  """卡名 ↔ 卡号，以及主卡组/额外卡组的划分。"""

  def __init__(self, cdb: Path, ydk: Path):
    self.connection = sqlite3.connect(cdb)
    self.names: dict[int, str] = {}
    self.codes: dict[str, int] = {}
    # texts 表里同一个卡名可能有多个 id（异画/复刻指向原卡），
    # 取 datas.alias == 0 的那张正卡，否则会拿到 +1 的异画号，匹配全失败。
    for row in self.connection.execute(
      "SELECT t.id, t.name, d.alias FROM texts t LEFT JOIN datas d ON d.id = t.id"
    ):
      card_id, name, alias = row
      self.names.setdefault(card_id, name)
      if name not in self.codes or not alias:
        self.codes[name] = card_id if not alias else self.codes.get(name, card_id)
    from probe import read_ydk

    deck = read_ydk(ydk)
    self.main = set(deck["main"])
    self.extra = set(deck["extra"])

  def code(self, name: str) -> int:
    return self.codes.get(name, 0)

  def markers(self, code: int) -> int:
    """连接标记。这一版 cards.cdb 把箭头存在 def 里（见 probe._link_marker）。"""
    row = self.connection.execute("SELECT type, def FROM datas WHERE id = ?", (code,)).fetchone()
    if not row:
      return 0
    type_code, defense = row
    if not type_code & TYPE_LINK:
      return 0
    return defense or 0

  def summon_target(self, text: str, *, extra: bool) -> int | None:
    """从自然语言里找出召唤的是哪张卡（优先额外卡组/主卡组对应区）。"""
    pool = self.extra if extra else self.main
    for code in pool:
      name = self.names.get(code, "")
      if name and name in text:
        return code
    return None


LOCATION_NAMES = {
  0x01: "DECK",
  0x02: "HAND",
  0x04: "MZONE",
  0x08: "SZONE",
  0x10: "GRAVE",
  0x20: "REMOVED",
  0x40: "EXTRA",
  0x80: "OVERLAY",
}


def short_name(name: str) -> str:
  """去掉 <系列> 前缀：「码丽丝<兵卒>白兔」→「白兔」。"""
  return re.sub(r"^[^<]*<[^>]+>", "", name)


def describe_location(value: int) -> str:
  return LOCATION_NAMES.get(value, hex(value))


def describe_card(card: dict, deck: Deck) -> str:
  """「白兔@MZONE1」——比只写卡名多一个「在哪」，选错地方时一眼看出。"""
  name = deck.names.get(card["code"], card["code"])
  return f"{name}@{describe_location(card['location'])}{card['sequence']}"


def target_codes(step: dict, deck: Deck) -> list[int]:
  """这一步要「选」的那张卡：`uses` 里除第一个（发动源/主角）以外的条目。

  选卡时必须用这个而不是整串：步骤写成「发动梦游地下界：除外睡鼠」时，
  整串里排在前面的正是地下界自己，而地下界本身也是可以除外的码丽丝卡，
  按整串匹配就会把地形自己除外掉。
  """
  uses = step.get("uses") or []
  codes = [deck.code(use["card"]) for use in uses[1:]]
  return [code for code in codes if code]


def primary_codes(step: dict, deck: Deck) -> list[int]:
  """这一步的「主角」：召唤目标，或 `uses` 第一条。

  idle 里挑动作用它：`uses` 里可能同时写着「发动的卡」和「被检索/被除外的卡」，
  而它们常常同在一张手牌里——按整串匹配会先撞上被检索的那张，把「发动星球改造」
  干成「直接发动地形」。
  """
  if step.get("action") in ("normal_summon", "link_summon"):
    # 召唤类步骤在 idle 里出现的是**要出场的怪兽**，素材只在选素材那一步才出现
    return expected_codes(step, deck)[:1]
  uses = step.get("uses") or []
  if uses:
    code = deck.code(uses[0]["card"])
    if code:
      return [code]
  return expected_codes(step, deck)


def expected_codes(step: dict, deck: Deck) -> list[int]:
  """这一步会出现哪些卡：召唤目标排最前，后面跟 `uses` 里的素材。

  召唤/连接召唤的 idle 里出现的是**要出场的怪兽**，素材只在选素材那一步出现，
  所以两边都要带上，否则加个 `uses` 就会把 idle 匹配弄坏。
  """
  codes = [deck.code(use["card"]) for use in step.get("uses") or []]
  codes = [code for code in codes if code]
  action = step.get("action")
  text = step.get("act", "")
  if action == "normal_summon":
    target = deck.summon_target(text, extra=False)
  elif action == "link_summon":
    target = deck.summon_target(text, extra=True)
  else:
    target = None
  if target:
    # 召唤目标永远排最前：素材也可能写在 uses 里，不能让它顶在前面
    codes = [target] + [code for code in codes if code != target]
  return codes


def material_codes(step: dict, deck: Deck) -> list[int]:
  """这一步的素材/祭品该用哪些卡。

  `uses` 里写全了就照它；没写就从步骤文本里认卡名（「睡鼠＋白兔连接召唤…」
  「柴郡猫 → 连接解码员」），认不出来就只能贪心选第一张。
  """
  codes = [deck.code(use["card"]) for use in step.get("uses") or []]
  codes = [code for code in codes if code]
  if codes:
    return codes
  text = step.get("act") or ""
  if not text:
    return []
  return [
    code for code, name in deck.names.items() if short_name(name) and short_name(name) in text
  ]


def describe_idle(idle: dict) -> str:
  parts = []
  for key in ("summon", "spsummon", "activate"):
    if idle.get(key):
      parts.append(f"{key}={[entry['code'] for entry in idle[key]]}")
  return " ".join(parts) or "（无动作）"


def run(args) -> int:
  deck = Deck(args.cdb, args.ydk)
  analysis = json.loads(args.analysis.read_text(encoding="utf-8-sig"))
  line = next(
    (item for item in analysis["combo_lines"] if item["name"].startswith(args.line)),
    analysis["combo_lines"][0],
  )
  steps = line["steps"]
  print(f"剧本：{line['name']}（{len(steps)} 步）\n")

  session = Session(args, args.seed)
  index = 0
  started = False
  idle_seen = 0
  log_seen = 0
  # 每一步在「选一张」的循环里已经点掉的卡号，避免同一张被反复选
  picked_codes: dict[int, set[int]] = {}
  # 「回完 idle 之后还没看到召唤/发动」的挂起动作：没有它，取消掉的召唤也会显示 ✓
  promise: dict | None = None
  # 怪兽区的位置模型：连接怪兽「指着哪」决定了后续能不能接上
  field = Field(deck)
  try:
    for _ in range(2000):
      status, buffer = session.step()
      if getattr(args, "logs", False):
        for line in session.logs[log_seen:]:
          print(f"      [日志] {line[:120]}")
        log_seen = len(session.logs)
      for message in msg.split(buffer):
        if getattr(args, "all", False):
          print("    .", message.name)
        if (
          promise
          and not promise["confirmed"]
          and (message.type in SUMMON_EVIDENCE or message.type in (MSG_CHAINING, MSG_MOVE))
        ):
          event = msg.decode_card_event(message)
          if event["code"] in promise["codes"]:
            promise["confirmed"] = True
            if args.trace:
              print(f"        [确认] {message.name} {event['code']} 真的发生了")
        if message.type == MSG_SELECT_IDLECMD:
          if started:
            if promise and not promise["confirmed"]:
              print(
                f"[M5d] 第 {index + 1} 步没有真的发生："
                f"没看到 {promise['codes']} 的召唤 / 发动（引擎把动作静默丢弃了）"
              )
              return 1
            print(f"  {index + 1:2d}. ✓ {steps[index]['act'][:48]}")
            index += 1
            started = False
            promise = None
          idle = msg.decode_idlecmd(message)
          if args.trace:
            print("        [空闲] " + describe_idle(idle))
          idle_seen += 1
          while index < len(steps) and steps[index].get("action") == "resolve":
            index += 1
          if index >= len(steps):
            print(f"[M5d] 通过：{len(steps)} 步全部执行完")
            return 0
          step = steps[index]
          action = step.get("action")
          # idle 里挑动作按「主角」匹配；选卡/选素材时才用整串 codes
          codes = primary_codes(step, deck)
          all_codes = expected_codes(step, deck)

          chosen = None
          if action == "normal_summon":
            chosen = next(
              ((msg.IDLE_SUMMON, i) for i, e in enumerate(idle["summon"]) if e["code"] in codes),
              None,
            )
          elif action == "link_summon":
            chosen = next(
              (
                (msg.IDLE_SPSUMMON, i) for i, e in enumerate(idle["spsummon"]) if e["code"] in codes
              ),
              None,
            )
          elif action in ("activate", "special_summon"):
            # 起动效果（手卡自跳、场上发动）走 activate 段；靠自身手续从额外/手卡
            # 出场的走 spsummon 段。两个都查，先按发动处理。
            chosen = next(
              (
                (msg.IDLE_ACTIVATE, i) for i, e in enumerate(idle["activate"]) if e["code"] in codes
              ),
              None,
            ) or next(
              (
                (msg.IDLE_SPSUMMON, i) for i, e in enumerate(idle["spsummon"]) if e["code"] in codes
              ),
              None,
            )

          if chosen is None:
            print(f"[M5d] 第 {index + 1} 步不可行：{step['act'][:40]}")
            print(
              f"       期望卡号 {codes}（本步涉及 {all_codes}），引擎给的是 {describe_idle(idle)}"
            )
            if session.logs:
              print(f"       引擎日志 {len(session.logs)} 条，最近 5 条：")
              for line in session.logs[-5:]:
                print(f"         {line[:160]}")
            return 1
          session.respond(msg.encode_idlecmd_response(*chosen))
          started = True
          promise = {"codes": codes, "confirmed": False}

        elif message.type == MSG_SELECT_EFFECTYN:
          choice = msg.decode_effectyn(message)
          # 下一步的诱发效果可能在上一步还没回到 idle 时就来问，优先级：下一步 > 当前步
          order = [index + 1, index] if started else [index]
          hit = None
          for candidate in order:
            if candidate >= len(steps):
              continue
            if choice["code"] in expected_codes(steps[candidate], deck):
              hit = candidate
              break
          if hit is not None:
            session.respond(msg.encode_yes_no(True))
            if hit > index:
              print(f"  {index + 1:2d}. ✓ {steps[index]['act'][:48]}")
              index = hit
            started = True
          else:
            session.respond(msg.encode_yes_no(False))

        elif message.type == MSG_SELECT_CHAIN:
          chain = msg.decode_chain(message)
          # 当前步骤还在等结算时，下一步的诱发效果可能已经作为连锁上来了
          # （白兔③ 就是 TB-11 那条连锁的第 2 环）。所以两个都试。
          order = [index + 1, index] if started else [index]
          target = None
          hit = index
          for candidate in order:
            if candidate >= len(steps):
              continue
            # 写着 `"via": "idle"` 的步骤必须在主阶段空闲时发动，不能从连锁窗口插进去：
            # 陷阱在「设置回合」发动时，只有走 idle 那条路才会收 SET_TURN 效果的费用
            # （链锁窗口里引擎会把费用漏掉），从连锁里插队等于白嫖，得到的线是假的。
            if steps[candidate].get("via") == "idle":
              if args.trace:
                print(f"        [连锁] 跳过步骤 {candidate + 1}：它是 idle 发动的")
              continue
            codes = expected_codes(steps[candidate], deck)
            if not codes:
              continue
            if args.trace:
              print(
                f"        [连锁] 候选步骤 {candidate + 1} 期望 {codes}，"
                f"窗口 {[e['code'] for e in chain['chains']]} forced={chain['forced']}"
              )
            found = next((i for i, e in enumerate(chain["chains"]) if e["code"] in codes), None)
            if found is not None:
              target, hit = found, candidate
              break
          if target is not None:
            session.respond(msg.encode_chain_response(target))
            if hit > index:
              print(f"  {index + 1:2d}. ✓ {steps[index]['act'][:48]}")
              index = hit
            started = True
          elif chain["forced"]:
            session.respond(msg.encode_chain_response(0))
          else:
            session.respond(msg.encode_chain_response(-1))

        elif message.type == MSG_SELECT_CARD:
          selection = msg.decode_select_card(message)
          step = steps[index] if index < len(steps) else None
          codes = expected_codes(step, deck) if step else []
          # 优先用「被选中的那张」，其次才退回整串
          prefer = target_codes(step, deck) if step else []
          if step:
            print(
              f"        [选卡] 步骤 {index + 1} 期望 {prefer or codes}，"
              f"候选 {[describe_card(card, deck) for card in selection['cards']]}"
            )
          preferred = next(
            (i for i, card in enumerate(selection["cards"]) if card["code"] in (prefer or codes)),
            None,
          )
          if preferred is None and step:
            # 步骤文本常用简称（「白兔」），库里是全名（「码丽丝<兵卒>白兔」），
            # 所以去掉 <系列> 前缀再比，否则会退回盲选第一个。
            text = step.get("act", "")
            preferred = next(
              (
                i
                for i, card in enumerate(selection["cards"])
                if short_name(deck.names.get(card["code"], "")) in text
              ),
              None,
            )
          if preferred is not None:
            chosen = [preferred]
          else:
            take = max(selection["min"], 1)
            chosen = list(range(min(take, len(selection["cards"]))))
          session.respond(msg.encode_card_response(chosen))

        elif message.type == MSG_SELECT_PLACE:
          place = msg.decode_place(message)
          zones = msg.zones_from_flag(place["flag"])
          zone = field.choose_zone(zones)
          if zone is None:
            return 1
          if zone >= 8:
            session.respond(msg.encode_place_response(place["player"], LOCATION_SZONE, zone - 8))
          else:
            session.respond(msg.encode_place_response(place["player"], LOCATION_MZONE, zone))
          if args.trace:
            print(f"        [放牌] 允许 {zones} → 选 {zone}（场：{field.describe()}）")

        elif message.type == MSG_SELECT_POSITION:
          position = msg.decode_position(message)
          session.respond(msg.encode_position(0x1 if position["positions"] & 0x1 else 0x4))

        elif message.type == MSG_SELECT_UNSELECT_CARD:
          # 连接素材就是这么选的：一次一张，引擎每收一张就重算一次是否已满足条件。
          # 想选的卡都选完就回 -1 结束；选错方向会直接进 MSG_RETRY 死循环。
          selection = msg.decode_select_unselect_card(message)
          codes = material_codes(steps[index], deck) if index < len(steps) else []
          picked = picked_codes.setdefault(index, set())
          candidates = [
            i
            for i, card in enumerate(selection["select"])
            if card["code"] in codes and card["code"] not in picked
          ]
          if not candidates:
            # 认不出素材时不要急着回 -1：那是「取消这次召唤」，引擎会安静地什么都不做，
            # 于是看起来像「上一步成功了」。选一张没选过的，让引擎自己判合法性。
            candidates = [
              i for i, card in enumerate(selection["select"]) if card["code"] not in picked
            ]
          if args.trace:
            print(
              f"        [选/退] 步骤 {index + 1} 期望 {codes}，"
              f"候选 {[card['code'] for card in selection['select']]}，"
              f"已选 {sorted(picked)}"
            )
          if candidates:
            chosen_index = candidates[0]
            picked.add(selection["select"][chosen_index]["code"])
            session.respond(msg.encode_unselect_card_response(chosen_index))
          else:
            session.respond(msg.encode_unselect_card_response(None))

        elif message.type == MSG_SELECT_YESNO:
          choice = msg.decode_yesno(message)
          session.respond(msg.encode_yes_no(True))
          if args.trace:
            print(f"        [是否] 玩家 {choice['player']} -> 是（desc={choice['description']}）")
        elif message.type == MSG_SELECT_OPTION:
          session.respond(bytes([0]))

        elif message.type == MSG_LPUPDATE and args.trace:
          player, lp = struct.unpack_from("<BI", message.payload, 0)
          print(f"        [LP] 玩家 {player} -> {lp}")

        elif message.type == MSG_PAY_LPCOST and args.trace:
          player, cost = struct.unpack_from("<BI", message.payload, 0)
          print(f"        [LP] 玩家 {player} 支付 {cost}")

        elif message.type == MSG_MOVE:
          move = msg.decode_move(message)
          field.update_from_move(move)
          if args.trace:
            name = deck.names.get(move["code"], move["code"])
            print(
              f"        [移动] {name}: "
              f"{describe_location(move['from']['location'])} -> "
              f"{describe_location(move['to']['location'])}"
            )

      if status == 0:
        print(f"[M5d] status=0 对局结束（走到第 {index + 1} 步）")
        return 1
    return 1
  finally:
    session.close()


def main(argv: list[str] | None = None) -> int:
  parser = argparse.ArgumentParser(description="M5d：按剧本驱动引擎。")
  parser.add_argument("--dll", type=Path, required=True)
  parser.add_argument("--cdb", type=Path, required=True)
  parser.add_argument("--ydk", type=Path, required=True)
  parser.add_argument(
    "--opponent-ydk",
    type=Path,
    help="对手改用另一套牌：邻家割草按双方卡组张数之差削牌，双方都 60 张会削 0 张",
  )
  parser.add_argument("--scripts", type=Path, required=True)
  parser.add_argument("--analysis", type=Path, required=True)
  parser.add_argument("--line", default="白兔线")
  parser.add_argument("--seed", type=int, default=8)
  parser.add_argument("--trace", action="store_true", help="打印连锁/选卡的候选")
  parser.add_argument("--all", action="store_true", help="打印全部消息名")
  parser.add_argument("--logs", action="store_true", help="打印引擎日志（脚本报错会出现在这里）")
  return run(parser.parse_args(argv))


if __name__ == "__main__":
  raise SystemExit(main())
