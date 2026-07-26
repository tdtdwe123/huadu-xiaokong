#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一键部署：把本地修正后的文件推送到 GitHub Pages 仓库。

推送方式：git clone(公开仓库) -> 仅覆盖指定的更新文件 -> 提交并 git push。
- 不改动站点其他资源（leaflet.js/css 等线上已有）。
- 28MB 的 data.json 走 git 协议，不受网页 25MB 限制。
- 需要写权限的 PAT（repo 权限；若要一并推送 Actions 工作流需 workflow 权限）。

用法：
  python3 deploy.py ghp_xxx                      # 明文传入 PAT
  GITHUB_TOKEN=ghp_xxx python3 deploy.py        # 环境变量传入
"""
import os, sys, shutil, subprocess, tempfile, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config

REPO = "tdtdwe123/huadu-xiaokong"
BASE = os.path.dirname(os.path.abspath(__file__))

# 仅覆盖这些文件（其余线上资源保持不变）
FILES = [
    "data.json", "projects.json", "fetch_status.json",
    "fetch_fast.py", "fetch_robust.py", "retry_failed.py", "build_projects.py",
    "fix_grouping.py", "apply_roster.py", "roster_overlay.json", "refetch_none_buildings.py",
    "push_all.py", "auto_update.py", "deploy.py", "config.py",
    "index.html", "aliases.json",
]
# 工作流文件：需要 token 具备 workflow 权限；失败则跳过并提示
WORKFLOWS = [
    ".github/workflows/fetch.yml",
    ".github/workflows/deploy-pages.yml",
]


def run(cmd, cwd=None, check=True):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"命令失败 {' '.join(cmd)}:\n{r.stderr}")
    return r


def main():
    token = (sys.argv[1] if len(sys.argv) > 1 else os.environ.get("GITHUB_TOKEN") or config.get_token())
    if not token or not token.startswith("ghp_"):
        print("✗ 未提供有效 GitHub Token。用法: python3 deploy.py <PAT> 或设置环境变量 GITHUB_TOKEN / 写入 .token")
        sys.exit(1)

    tmp = tempfile.mkdtemp(prefix="huadu_deploy_")
    clone_url = f"https://{token}@github.com/{REPO}.git"
    print(f"[1/4] 克隆仓库到 {tmp} …")
    run(["git", "clone", "--depth", "1", clone_url, tmp], check=True)

    print(f"[2/4] 覆盖更新文件（{len(FILES)} 个）…")
    for f in FILES:
        src = os.path.join(BASE, f)
        if not os.path.exists(src):
            print(f"  - 跳过缺失的 {f}")
            continue
        dst = os.path.join(tmp, f)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        print(f"  ✓ {f}")

    # 工作流（需要 workflow 权限）
    for wf in WORKFLOWS:
        wf_src = os.path.join(BASE, wf)
        if os.path.exists(wf_src):
            try:
                shutil.copy2(wf_src, os.path.join(tmp, wf))
                print(f"  ✓ {wf}")
            except Exception as e:
                print(f"  ! 工作流复制失败（可能需 workflow 权限）: {wf} {e}")

    print("[3/4] 提交变更…")
    run(["git", "add", "-A"], cwd=tmp)
    # 若没有任何变化则跳过提交
    st = run(["git", "status", "--porcelain"], cwd=tmp, check=True)
    if not st.stdout.strip():
        print("  无文件变化，无需提交。")
    else:
        msg = f"自动更新销控数据 + 补全楼盘至657 + 修复自动更新 ({time.strftime('%Y-%m-%d %H:%M')})"
        run(["git", "-c", "user.email=bot@local", "-c", "user.name=huadu-bot",
             "commit", "-m", msg], cwd=tmp)
        print("  已提交。")

    print("[4/4] 推送到 GitHub …")
    run(["git", "push", "origin", "main"], cwd=tmp)
    print("\n✅ 部署完成。GitHub Pages 约 1-2 分钟后重建生效。")
    print(f"   站点: https://tdtdwe123.github.io/huadu-xiaokong/")


if __name__ == "__main__":
    main()
