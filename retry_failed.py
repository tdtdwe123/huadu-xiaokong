#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""针对 data.json 中 detail 为空的楼盘做定向补抓。
设计要点：
  - 每成功补抓一条【立即写回 data.json】，避免进程被中断时前功尽弃。
  - 3 线程并发 + 中等重试（retries=3, timeout=25）：快进快出，
    瞬断项基本能救回；官方确实查不到的「真失败」项最多 ~1.5 分钟放弃。
  - 多轮扫描：直到一轮无任何新进展或达到 MAX_PASS 轮。
"""
import json, os, sys, time, threading
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fetch_robust as FR

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data.json")
PROJ = os.path.join(BASE, "projects.json")

RETRIES = 3
TIMEOUT = 40
WORKERS = 1
MAX_PASS = 3


def save(d, lock):
    with lock:
        json.dump(d, open(DATA, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))


def main():
    d = json.load(open(DATA, encoding="utf-8"))
    pj = json.load(open(PROJ, encoding="utf-8"))
    by_id = {p["id"]: p for p in pj}
    lock = threading.RLock()  # 可重入：save() 在持有锁时再次加锁不会死锁
    done_total = [0]

    def work(p):
        try:
            det = FR.fetch_project(p["id"], retries=RETRIES, timeout=TIMEOUT)
        except Exception:
            det = None
        if det:
            with lock:
                p["detail"] = det
                src = by_id.get(p["id"])
                if src:
                    p["lng"], p["lat"] = src.get("lng"), src.get("lat")
                    p["geo_approx"] = src.get("geo_approx")
                    p["geo_src"] = src.get("geo_src")
                done_total[0] += 1
                save(d, lock)  # 立即落盘，防中断丢失
                print(f"  ✓ 补抓成功 {p['name']} (累计{done_total[0]})", flush=True)
            return True
        print(f"  ✗ 仍失败 {p['name']}", flush=True)
        return False

    for pas in range(1, MAX_PASS + 1):
        failed = [p for p in d["projects"] if not p.get("detail")]
        if not failed:
            print("全部已补齐，无需补抓。")
            break
        before = done_total[0]
        print(f"\n=== 第 {pas}/{MAX_PASS} 轮：待补 {len(failed)} 个 ===", flush=True)
        with ThreadPoolExecutor(max_workers=WORKERS) as ex:
            list(ex.map(work, failed))
        after = done_total[0]
        still = sum(1 for p in d["projects"] if not p.get("detail"))
        print(f"本轮新增 {after - before} 个，仍为空 {still} 个", flush=True)
        if after == before:
            print("本轮无新进展，停止扫描（剩余为官方确实查不到的项目）。")
            break

    still = sum(1 for p in d["projects"] if not p.get("detail"))
    print(f"\n补抓结束：累计成功 {done_total[0]} 个，仍为空 {still} 个；data.json 已写回。")
    if still:
        print("仍为空的项目（官方接口无数据，地图仍会显示其位置标记）：")
        for p in d["projects"]:
            if not p.get("detail"):
                print(f"  - {p['id']} | {p.get('area') or '∅'} | {p['name']}")


if __name__ == "__main__":
    main()
