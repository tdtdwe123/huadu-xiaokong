#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把本地文件一次性推送到 GitHub（Contents API）。

Token 解析（见 config.get_token）：环境变量 GITHUB_TOKEN -> 本地 .token 文件。
用法：python3 push_all.py            # 推送默认清单
      python3 push_all.py data.json   # 只推送指定文件
"""
import os, base64, time, sys
import requests
import config

BASE = os.path.dirname(os.path.abspath(__file__))
REPO = "tdtdwe123/huadu-xiaokong"
API = f"https://api.github.com/repos/{REPO}"

# 默认推送清单（站点数据 + 抓取/更新管线）
FILES = [
    "data.json", "projects.json", "fetch_status.json",
    "fetch_fast.py", "fetch_robust.py", "retry_failed.py", "build_projects.py",
    "push_all.py", "auto_update.py", "deploy.py", "config.py", "index.html",
    "aliases.json",
]


def _headers(token):
    return {"Authorization": f"token {token}", "Accept": "application/vnd.github+json"}


def push(path, token, force=False):
    full = os.path.join(BASE, path)
    if not os.path.exists(full):
        print(f"  - {path} 不存在，跳过")
        return False
    with open(full, "rb") as f:
        data = f.read()
    H = _headers(token)
    r = requests.get(f"{API}/contents/{path}", headers=H, timeout=30)
    sha = r.json().get("sha") if r.status_code == 200 else None
    if not force and r.status_code == 200:
        remote = base64.b64decode(r.json().get("content", ""))
        if remote == data:
            print(f"  = {path} 内容未变，跳过")
            return True
    body = {"message": f"自动更新销控数据 ({time.strftime('%Y-%m-%d %H:%M')})",
            "branch": "main", "content": base64.b64encode(data).decode()}
    if sha:
        body["sha"] = sha
    r = requests.put(f"{API}/contents/{path}", headers=H, timeout=120, json=body)
    if r.status_code in (200, 201):
        print(f"  ✓ {path} 已推送")
        return True
    print(f"  ✗ {path} 失败 {r.status_code}: {r.text[:200]}")
    return False


def push_all(token=None, targets=None):
    token = token or config.get_token()
    targets = targets or FILES
    H = _headers(token)
    probe = requests.get(f"{API}", headers=H, timeout=20)
    if probe.status_code == 401:
        print("✗ GitHub Token 无效(401)。请设置有效 GITHUB_TOKEN（repo 权限）或写入 .token 后重试。")
        return False
    print(f"[{time.strftime('%H:%M:%S')}] 推送 {len(targets)} 个文件…", flush=True)
    ok = 0
    for t in targets:
        if push(t, token):
            ok += 1
    print(f"[{time.strftime('%H:%M:%S')}] 推送完成 {ok}/{len(targets)}。GitHub Pages 约 1-2 分钟重建生效。")
    return ok == len(targets)


if __name__ == "__main__":
    push_all(targets=(sys.argv[1:] or None))
