"""打印某颗种子的起手空闲命令，用于排查「割草不在手卡」。"""

from __future__ import annotations

import argparse
from pathlib import Path

import messages as msg
from m5a import Session
from ocg_constants import MSG_SELECT_IDLECMD

DECK60 = Path(r"D:\dsharness-work\ygo-ai\decks\割草白雪奥艺码丽丝.ydk")
DECK40 = Path(r"D:\dsharness-work\ygo-ai\decks\奥艺码丽丝.ydk")


def main() -> int:
  parser = argparse.ArgumentParser()
  parser.add_argument("--dll", type=Path, required=True)
  parser.add_argument("--cdb", type=Path, required=True)
  parser.add_argument("--scripts", type=Path, required=True)
  parser.add_argument("--seed", type=int, default=28)
  args = parser.parse_args()
  args.ydk = DECK60
  args.opponent_ydk = DECK40

  session = Session(args, args.seed)
  try:
    for _ in range(50):
      _, buffer = session.step()
      for message in msg.split(buffer):
        if message.type == MSG_SELECT_IDLECMD:
          idle = msg.decode_idlecmd(message)
          print("summon   ", [entry["code"] for entry in idle["summon"]])
          print("spsummon ", [entry["code"] for entry in idle["spsummon"]])
          print("activate ", [entry["code"] for entry in idle["activate"]])
          return 0
  finally:
    session.close()
  return 1


if __name__ == "__main__":
  raise SystemExit(main())
