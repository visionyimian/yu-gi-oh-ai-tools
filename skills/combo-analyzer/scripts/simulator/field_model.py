"""场上怪兽的位置模型：只回答一个问题——哪些格子被自己的连接怪兽指着。

为什么需要它：连接怪兽「指向的区域」是从它站的位置和箭头算出来的，同一个箭头
站在主要怪兽区和站在额外怪兽区指向完全不同的格子。程序如果一律把怪兽放到最左边
的格子，依赖「指向」的诱发效果（小男巫③：连接端特殊召唤成功时检索）就永远不会触发，
表现成「连接召唤成功了，但后续步骤查不到那只怪兽的效果」。

箭头编号照抄 card.cpp 的 LINK_MARKER_*（ocgapi_constants.h 里写的是八进制）。
"""

from __future__ import annotations

LINK_MARKER_BOTTOM_LEFT = 0x001
LINK_MARKER_BOTTOM = 0x002
LINK_MARKER_BOTTOM_RIGHT = 0x004
LINK_MARKER_LEFT = 0x008
LINK_MARKER_RIGHT = 0x020
LINK_MARKER_TOP_LEFT = 0x040
LINK_MARKER_TOP = 0x080
LINK_MARKER_TOP_RIGHT = 0x100

# 主要怪兽区 0..4，额外怪兽区 5、6（玩家 0 的视角）
MAIN_ZONES = (0, 1, 2, 3, 4)
EXTRA_MONSTER_ZONES = (5, 6)


def linked_zones(sequence: int, marker: int) -> set[int]:
  """攻击表示的连接怪兽站在 sequence 时，自己的主要怪兽区里有哪些被它指着。

  对照 card.cpp 的 `card::get_linked_zone`：站在主要怪兽区（0..4）时左右箭头连相邻格；
  站在额外怪兽区（5、6）时朝下的箭头才落进主要怪兽区。
  """
  zones: set[int] = set()
  if sequence in MAIN_ZONES:
    if sequence > 0 and marker & LINK_MARKER_LEFT:
      zones.add(sequence - 1)
    if sequence <= 3 and marker & LINK_MARKER_RIGHT:
      zones.add(sequence + 1)
    # 站在主要怪兽区时朝上的箭头指向额外怪兽区
    if (
      (sequence == 0 and marker & LINK_MARKER_TOP_RIGHT)
      or (sequence == 1 and marker & LINK_MARKER_TOP)
      or (sequence == 2 and marker & LINK_MARKER_TOP_LEFT)
    ):
      zones.add(5)
    if (
      (sequence == 2 and marker & LINK_MARKER_TOP_RIGHT)
      or (sequence == 3 and marker & LINK_MARKER_TOP)
      or (sequence == 4 and marker & LINK_MARKER_TOP_LEFT)
    ):
      zones.add(6)
  elif sequence == 5:
    if marker & LINK_MARKER_BOTTOM_LEFT:
      zones.add(0)
    if marker & LINK_MARKER_BOTTOM:
      zones.add(1)
    if marker & LINK_MARKER_BOTTOM_RIGHT:
      zones.add(2)
  elif sequence == 6:
    if marker & LINK_MARKER_BOTTOM_LEFT:
      zones.add(2)
    if marker & LINK_MARKER_BOTTOM:
      zones.add(3)
    if marker & LINK_MARKER_BOTTOM_RIGHT:
      zones.add(4)
  return zones


class Field:
  """玩家 0 的怪兽区。只跟踪位置和卡号，够算「指向」就行。"""

  def __init__(self, deck):
    self.deck = deck
    self.monsters: dict[int, int] = {}

  def place(self, zone: int, code: int) -> None:
    self.monsters[zone] = code

  def remove(self, zone: int) -> None:
    self.monsters.pop(zone, None)

  def linked(self) -> set[int]:
    """自己所有连接怪兽指着的格子。"""
    zones: set[int] = set()
    for sequence, code in self.monsters.items():
      marker = self.deck.markers(code)
      if marker:
        zones |= linked_zones(sequence, marker)
    return zones

  def update_from_move(self, move: dict) -> None:
    previous, current = move["from"], move["to"]
    if previous["controller"] == 0 and previous["location"] == 4:
      self.remove(previous["sequence"])
    if current["controller"] == 0 and current["location"] == 4:
      self.place(current["sequence"], move["code"])

  def describe(self) -> str:
    if not self.monsters:
      return "（空场）"
    parts = []
    for zone in sorted(self.monsters):
      name = self.deck.names.get(self.monsters[zone], self.monsters[zone])
      label = f"额外{zone - 4}" if zone >= 5 else f"主要{zone}"
      parts.append(f"{label}={name}")
    return " ".join(parts)

  def choose_zone(self, allowed: list[int]) -> int | None:
    """在有资格的格子里挑一个：优先「被自己连接怪兽指着」，其次额外怪兽区。

    被指着的位置优先，是因为码丽丝的扩展全靠连端怪兽把效果接下去；
    先站额外怪兽区是因为额外怪兽区朝下的箭头能覆盖两个主要怪兽区。
    """
    main = [zone for zone in allowed if zone in MAIN_ZONES or zone in EXTRA_MONSTER_ZONES]
    linked = sorted(set(main) & self.linked())
    if linked:
      return linked[0]
    extra = [zone for zone in main if zone in EXTRA_MONSTER_ZONES]
    if extra:
      return extra[0]
    if main:
      return main[0]
    spell = sorted(zone for zone in allowed if zone >= 8)
    return spell[0] if spell else None
