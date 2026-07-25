#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""自动更新主循环（快速差分抓取 + 主动推送）。

流程：
  1) fetch_fast.main()  —— 差分抓取：轻量摘要全量扫，只对「无数据/有变动」的盘做完整抓取。
  2) 若本轮数据发生变化（fetch_status.changed）或距上次强制推送超过阈值
     → push_all() 主动推送，无需人工触发。
  3) 休眠后循环。

Token：优先环境变量 GITHUB_TOKEN（export GITHUB_TOKEN=ghp_xxx 后重启本进程）。
       未设置/失效时，抓取照常进行（本地数据保持最新），仅跳过推送并提示。
"""
import os, time, sys, json

BASE = "/workspace/huadu_map/github_pages"
sys.path.insert(0, BASE)
import config
import fetch_fast
import push_all

TOKEN = config.get_token()

FORCE_PUSH_EVERY = 6 * 3600   # 即便无变化，每 6 小时也强制保底推送一次
SLEEP_SEC = 300               # 每轮之间休眠 5 分钟（抓取本身约 30 分钟，故实际节奏≈抓取耗时）


def main():
    last_force = 0.0
    while True:
        try:
            print(f"[{time.strftime('%H:%M:%S')}] === 开始快速差分抓取 ===", flush=True)
            status = fetch_fast.main()
            now = time.time()
            changed = status.get("changed")
            force = (now - last_force) >= FORCE_PUSH_EVERY
            if changed or force:
                reason = "数据有变动" if changed else "定时保底"
                print(f"[{time.strftime('%H:%M:%S')}] 推送触发（{reason}）", flush=True)
                push_all.push_all(TOKEN)
                last_force = now
            else:
                print(f"[{time.strftime('%H:%M:%S')}] 无变化，跳过推送。", flush=True)
        except Exception as e:
            print(f"[{time.strftime('%H:%M:%S')}] 循环异常: {e}", flush=True)
        print(f"[{time.strftime('%H:%M:%S')}] 休眠 {SLEEP_SEC}s 后继续…", flush=True)
        time.sleep(SLEEP_SEC)


if __name__ == "__main__":
    main()
