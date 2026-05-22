# Codex 操作教程：从零搭建 GSC 到飞书多维表格同步

本文面向 **Codex 代理**，目标是帮助另一个用户从零配置 Google Search Console（GSC）数据同步到飞书多维表格，并可选部署到 GitHub Actions 定时运行。

当前仓库方案默认同步 GSC 的周汇总数据：`clicks`、`impressions`。脚本会按 `唯一键` 更新已有记录，避免重复插入。

## 0. Codex 执行原则

先保护密钥，再做自动化：

- 不要把 `.env`、`.secrets/`、Google OAuth token、Google client secret、飞书 app secret 提交到 git。
- 如果用户把密钥贴到聊天里，提醒他们跑通后重新生成密钥并废弃旧密钥。
- 优先使用当前仓库已有脚本，不要重写整套方案。
- 修改代码前先看文件；运行前先确认 `.gitignore` 覆盖敏感文件。
- 如果要推 GitHub，先确认 `git status --short --ignored` 里 `.env` 和 `.secrets/` 是 ignored。

需要向用户收集的信息：

```text
GSC_SITE_URL=Search Console 资源名，例如 sc-domain:example.com 或 https://www.example.com/
Google OAuth client JSON，通常是 {"installed": {...}} 结构
飞书多维表格完整 URL
FEISHU_APP_ID=cli_xxx
FEISHU_APP_SECRET=xxx
GitHub 仓库地址，可选
期望定时运行时间，例如每天北京时间 24:00
```

## 1. 准备仓库

如果用户已经 clone 了本仓库，先进入目录：

```powershell
cd "<用户的项目目录>"
```

检查文件：

```powershell
git status --short --ignored
rg --files -uu
```

当前方案核心文件应包含：

```text
sync_gsc_weekly_to_feishu.py
requirements.txt
.env.example
.gitignore
.github/workflows/sync-gsc-feishu.yml
run_sync.ps1
setup_windows_task.ps1
```

安装依赖：

```powershell
python -m pip install -r requirements.txt
python -m py_compile sync_gsc_weekly_to_feishu.py
```

## 2. 配置 Google Search Console

### 2.1 确认 GSC 资源

让用户打开 Search Console，确认要同步的网站资源名：

- 域名资源格式：`sc-domain:example.com`
- URL 前缀资源格式：`https://www.example.com/`

脚本里的 `GSC_SITE_URL` 必须和 Search Console 资源完全一致。

### 2.2 创建 Google Cloud 项目和 OAuth 凭据

让用户在 Google Cloud Console 中操作：

1. 创建或选择一个项目。
2. 启用 **Google Search Console API**。
3. 配置 OAuth consent screen。
4. 创建 OAuth client：
   - Application type 选 **Desktop app**。
   - 下载 JSON。
5. 如果 OAuth 应用仍在 Testing，确保把要授权的 Google 账号加入 test users。

本仓库使用用户 OAuth token。首次本地授权成功后，会生成 `.secrets/gsc_token.json`，GitHub Actions 后续使用这个 token JSON 作为 Secret。

官方参考：

- [Google Search Console API 授权](https://developers.google.com/webmaster-tools/v1/how-tos/authorizing)
- [Search Analytics query API](https://developers.google.com/webmaster-tools/v1/searchanalytics/query)

## 3. 配置飞书开放平台

### 3.1 创建飞书自建应用

让用户进入飞书开放平台：

1. 创建 **企业自建应用**。
2. 记录：
   - `FEISHU_APP_ID`，通常以 `cli_` 开头。
   - `FEISHU_APP_SECRET`。
3. 开通多维表格相关权限。

推荐先开通较完整的多维表格权限：

```text
bitable:app
```

如果用户只能开细分权限，至少需要：

```text
base:field:read
base:field:create
base:record:retrieve
base:record:create
base:record:update
```

开权限后必须发布或启用应用新版本，否则 API 仍会报权限不足。

### 3.2 准备多维表格

让用户新建或打开一个飞书多维表格，复制完整 URL。

示例：

```text
https://xxx.feishu.cn/base/H8jKbHg8fapSi0stwkTcO6l2nGf?table=tblU2dqd507qcDjv&view=vewxxxx
```

解析方式：

```text
FEISHU_APP_TOKEN=H8jKbHg8fapSi0stwkTcO6l2nGf
FEISHU_TABLE_ID=tblU2dqd507qcDjv
```

如果链接是 `/wiki/` 形态，不要直接截 URL；需要按飞书文档获取多维表格的真实 `app_token`。

脚本会自动检查并补齐这些字段：

```text
站点
周开始日期
周结束日期
点击
展现
唯一键
同步时间
```

官方参考：

- [飞书自建应用 tenant_access_token](https://open.feishu.cn/document/server-docs/authentication-management/access-token/tenant_access_token_internal)
- [飞书多维表格新增记录](https://open.feishu.cn/document/server-docs/docs/bitable-v1/app-table-record/create)

## 4. 配置本地 `.env`

不要提交 `.env`。确认 `.gitignore` 包含：

```text
.env
.env.*
!.env.example
.secrets/
credentials/
logs/
exports/
__pycache__/
*.pyc
.venv/
```

创建 `.env`：

```env
GSC_SITE_URL=sc-domain:example.com
GOOGLE_CLIENT_SECRET_FILE=credentials/google_oauth_client.json
GOOGLE_TOKEN_FILE=.secrets/gsc_token.json

FEISHU_APP_ID=cli_xxx
FEISHU_APP_SECRET=xxx
FEISHU_APP_TOKEN=base_or_app_token
FEISHU_TABLE_ID=tblxxx
```

把 Google OAuth client JSON 保存到：

```text
credentials/google_oauth_client.json
```

如果用户直接给的是一整段 JSON，也可以临时用环境变量 `GOOGLE_OAUTH_CLIENT_JSON`，但更推荐保存到 ignored 的 credentials 目录。

## 5. 首次本地授权与同步

首次运行会弹出 Google 登录授权页。必须用拥有目标 GSC 资源权限的 Google 账号授权。

先干运行，只拉 GSC，不写飞书：

```powershell
python .\sync_gsc_weekly_to_feishu.py --month 2026-05 --through 2026-05-20 --dry-run --output exports/gsc_weekly_test.json
```

确认数据正常后写入飞书：

```powershell
python .\sync_gsc_weekly_to_feishu.py --month 2026-05 --through 2026-05-20 --output exports/gsc_weekly_test.json
```

验证去重更新逻辑：重复运行同一条命令，预期第一次是 `created > 0`，第二次是 `updated > 0`。

日常运行可以不传月份，脚本默认同步当前月份：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\run_sync.ps1
```

## 6. GitHub Actions 自动运行

### 6.1 workflow 文件

当前 workflow：

```text
.github/workflows/sync-gsc-feishu.yml
```

如果用户要求每天北京时间 24:00 运行，cron 应为：

```yaml
- cron: "0 16 * * *"
```

原因：GitHub Actions cron 使用 UTC，北京时间 24:00 等于 UTC 16:00。

GitHub 定时任务可能延迟几分钟，这是平台行为。

### 6.2 设置 GitHub Secrets

在 GitHub 仓库中设置这些 repository secrets：

```text
GSC_SITE_URL
GOOGLE_TOKEN_JSON
FEISHU_APP_ID
FEISHU_APP_SECRET
FEISHU_APP_TOKEN
FEISHU_TABLE_ID
```

本地复制 Google token：

```powershell
Get-Content ".secrets\gsc_token.json" -Raw | Set-Clipboard
```

然后粘贴到 GitHub Secret：`GOOGLE_TOKEN_JSON`。

也可以用 GitHub CLI 设置：

```powershell
gh secret set GSC_SITE_URL --body "sc-domain:example.com" -R <owner>/<repo>
gh secret set FEISHU_APP_ID --body "cli_xxx" -R <owner>/<repo>
gh secret set FEISHU_APP_SECRET --body "xxx" -R <owner>/<repo>
gh secret set FEISHU_APP_TOKEN --body "base_or_app_token" -R <owner>/<repo>
gh secret set FEISHU_TABLE_ID --body "tblxxx" -R <owner>/<repo>
Get-Content -Raw ".secrets\gsc_token.json" | gh secret set GOOGLE_TOKEN_JSON -R <owner>/<repo>
```

### 6.3 推送到 GitHub

只提交非敏感文件：

```powershell
git status --short --ignored
git add .gitignore .env.example requirements.txt sync_gsc_weekly_to_feishu.py run_sync.ps1 setup_windows_task.ps1 .github/workflows/sync-gsc-feishu.yml CODEX_SETUP_GUIDE.md
git commit -m "Add GSC to Feishu sync guide"
git remote add origin https://github.com/<owner>/<repo>.git
git branch -M main
git push -u origin main
```

如果 remote 已存在：

```powershell
git remote set-url origin https://github.com/<owner>/<repo>.git
git push -u origin main
```

### 6.4 云端验证

手动触发一次 workflow：

```powershell
gh workflow run sync-gsc-feishu.yml -R <owner>/<repo> --ref main -f month=2026-05 -f through=2026-05-20
gh run list -R <owner>/<repo> --workflow sync-gsc-feishu.yml --limit 3
```

查看最近一次运行：

```powershell
gh run view <run_id> -R <owner>/<repo> --log
```

成功后，飞书表里应看到记录被新增或更新。

## 7. Windows 本机定时运行，可选

如果用户不想用 GitHub Actions，也可以在 Windows 上注册任务计划程序：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup_windows_task.ps1 -Time "00:00"
```

手动触发：

```powershell
Start-ScheduledTask -TaskName "GSC Weekly To Feishu"
Get-ScheduledTaskInfo -TaskName "GSC Weekly To Feishu"
```

日志位置：

```text
logs/
```

## 8. 常见问题

### GSC 报 403 或没有站点权限

检查：

- `GSC_SITE_URL` 是否和 Search Console 资源完全一致。
- 授权的 Google 账号是否能在 Search Console 里看到该资源。
- OAuth 是否用了正确账号；必要时删除 `.secrets/gsc_token.json` 后重新授权。

### 飞书报 99991672 权限不足

检查：

- 飞书应用是否开通了 `bitable:app` 或对应细分权限。
- 开权限后是否发布了应用新版本。
- 多维表格是否允许该应用访问。
- `FEISHU_APP_TOKEN` 和 `FEISHU_TABLE_ID` 是否从正确 URL 解析。

### GitHub Actions 中 Google token 失效

检查：

- `GOOGLE_TOKEN_JSON` 是否是完整 `.secrets/gsc_token.json` 内容。
- token JSON 是否包含 `refresh_token`、`client_id`、`client_secret`。
- Google OAuth app 是否被删除或 client secret 是否被轮换。

如果轮换了 Google OAuth client secret，重新本地授权，更新 GitHub Secret `GOOGLE_TOKEN_JSON`。

### 数据和 GSC 页面不完全一致

GSC Search Analytics API 使用 PT 日期，并且 recent data 可能未最终稳定。脚本默认 `dataState=final`，更适合日报/周报稳定同步。如果用户想包含最新未定稿数据，可以传：

```powershell
python .\sync_gsc_weekly_to_feishu.py --data-state all
```

## 9. 默认数据口径

当前脚本逻辑：

- 按自然周切分，周一到周日。
- 月初/月末不足一周时按月内边界截断。
- 默认同步当前月份，截至今天。
- 不传 `dimensions`，GSC 返回该站点整体汇总。
- `aggregationType=byProperty`。
- `唯一键=站点|周开始日期|周结束日期`。

如果用户要同步关键词、页面、国家、设备，需要扩展脚本：

```text
dimensions=["query", "page", "country", "device"]
唯一键增加 query/page/country/device
飞书字段增加 查询词、页面、国家、设备、CTR、平均排名
分页处理 rowLimit=25000 和 startRow
```

扩展前先提醒用户：维度越细，GSC API 返回行数和飞书写入量会明显增加。
