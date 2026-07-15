# 花都区新盘销控表 — GitHub Pages 部署指南

## 这个方案是什么

把楼盘列表和销控数据放到 **GitHub Pages**（免费静态托管），用 **GitHub Actions** 每小时自动抓取最新销控数据。不需要后端服务器、不需要 CORS 代理，手机和电脑都能直接访问，链接永久有效。

## 你需要做什么（约 10 分钟）

### 第 1 步：注册 GitHub 账号（2 分钟）

1. 打开 https://github.com/signup
2. 填邮箱、设密码、取用户名，完成注册
3. 验证邮箱

### 第 2 步：创建新仓库（1 分钟）

1. 登录后点右上角 **+** → **New repository**
2. Repository name 填：`huadu-xiaokong`
3. 选择 **Public**（必须公开，GitHub Pages 免费版只支持公开仓库）
4. 勾选 **Add a README file**
5. 点 **Create repository**

### 第 3 步：上传项目文件（3 分钟）

1. 在本目录 `github_pages/` 下有这些文件：
   ```
   index.html          ← 网页
   projects.json       ← 254 个楼盘清单
   fetch_data.py       ← 数据抓取脚本
   data.json           ← 实时销控数据（首次运行后生成）
   .github/workflows/fetch.yml  ← 自动更新配置
   ```
2. 在 GitHub 仓库页面点 **Add file** → **Upload files**
3. 把 `index.html`、`projects.json`、`fetch_data.py`、`data.json` 拖进去
4. 点 **Commit changes**
5. 再上传 `.github/workflows/fetch.yml`：
   - 先点 **Create new file**
   - 文件名输入 `.github/workflows/fetch.yml`（注意有点号）
   - 把 `fetch.yml` 的内容粘贴进去
   - 点 **Commit new file**

> 提示：`data.json` 如果太大无法通过网页上传，可以先不上传，第 5 步手动运行 Action 会自动生成。

### 第 4 步：开启 GitHub Pages（1 分钟）

1. 进入仓库 → **Settings** → 左侧 **Pages**
2. **Source** 选 **Deploy from a branch**
3. **Branch** 选 `main`，文件夹选 `/ (root)`
4. 点 **Save**
5. 等 1-2 分钟，刷新页面会显示你的网址：
   ```
   https://你的用户名.github.io/huadu-xiaokong/
   ```

### 第 5 步：触发首次数据抓取（1 分钟）

1. 进入仓库 → **Actions** 标签页
2. 左侧选 **更新销控数据**
3. 点 **Run workflow** → **Run workflow**
4. 等 5-10 分钟跑完（254 个楼盘逐个抓取）
5. 跑完后刷新网页，销控数据就出来了

之后每小时自动更新一次，无需手动操作。

## 常见问题

**Q: 网页打开是空白？**  
A: 等第 5 步的 Action 跑完生成 `data.json` 后再刷新。

**Q: Action 运行失败？**  
A: 在 Actions 页面点进失败的运行，查看日志。常见原因是阳光家缘临时限流，重跑一次即可。

**Q: 数据多久更新一次？**  
A: 每小时整点自动更新。你也可以在 Actions 页面手动 **Run workflow** 立即更新。

**Q: 链接能分享给别人吗？**  
A: 可以，`https://你的用户名.github.io/huadu-xiaokong/` 是公开网址，任何人都能访问。

**Q: 要花钱吗？**  
A: GitHub Pages 和 Actions 对公开仓库完全免费，每月 2000 分钟 Actions 额度远够用（每次约 15 分钟，每月约 720 分钟）。
