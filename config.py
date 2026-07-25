#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""统一解析 GitHub Token：环境变量 GITHUB_TOKEN -> 本地 .token 文件 -> 兜底常量。
零摩擦接入：仓库所有者生成一次 PAT 后，粘贴给本 agent，由 agent 写入 .token，
之后 auto_update / push_all / deploy 自动读取，无需每次手工设置。
"""
import os

BASE = os.path.dirname(os.path.abspath(__file__))
TOKEN_FILE = os.path.join(BASE, ".token")
_FALLBACK = ""  # 无兜底常量：必须显式提供 token（环境变量 / .token），杜绝密钥泄露


def get_token():
    t = os.environ.get("GITHUB_TOKEN")
    if t:
        return t
    if os.path.exists(TOKEN_FILE):
        try:
            s = open(TOKEN_FILE, encoding="utf-8").read().strip()
            if s:
                return s
        except Exception:
            pass
    return _FALLBACK


def save_token(token: str):
    """把 token 持久化到 .token（gitignore 已忽略，不会被推送）。"""
    with open(TOKEN_FILE, "w", encoding="utf-8") as f:
        f.write(token.strip())
    os.chmod(TOKEN_FILE, 0o600)
    print(f"已保存 token 到 {TOKEN_FILE}（已设 600 权限，且被 .gitignore 忽略）")
