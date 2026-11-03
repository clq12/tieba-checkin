# 贴吧全自动签到

基于百度贴吧**客户端接口 + MD5 签名**的全量签到脚本，每天自动签到所有关注的贴吧。

- 客户端接口签到，单次 **+8 经验**（web 端接口只有基础经验）
- 自动翻页拉全部关注贴吧，**突破单页 200 条限制**（实测 1093 个吧一次拉全）
- 失败贴吧自动进入第二轮重试
- 长跑自动刷新 `tbs`，避免中途过期
- 可选微信/企业微信推送

## 快速开始（本地）

```bash
pip install -r requirements.txt

# Windows PowerShell
$env:BDUSS="你的BDUSS"; python tieba_sign.py

# Linux / macOS / Git Bash
BDUSS="你的BDUSS" python tieba_sign.py
```

只想试一小部分，加 `MAX_FORUMS`：

```bash
BDUSS="xxx" MAX_FORUMS=20 python tieba_sign.py
```

## 快速开始（GitHub Actions，推荐）

1. **Fork / 新建仓库**，把本目录推上去（**建议设为 Public**，Actions 不计分钟数）
2. **获取 BDUSS**：浏览器登录 [贴吧](https://tieba.baidu.com) → `F12` → Application → Cookies → `tieba.baidu.com` → 复制 `BDUSS` 的 Value
3. **添加 Secrets**：仓库 → Settings → Secrets and variables → Actions → New repository secret

   | Name | 必填 | 说明 |
   |---|---|---|
   | `BDUSS` | 是 | 贴吧登录凭证 |
   | `STOKEN` | 否 | 备用，`tieba.baidu.com` 域下的那个 |
   | `PUSH_TYPE` | 否 | `serverchan` / `pushplus` / `wecom` |
   | `PUSH_KEY` | 否 | 对应渠道的 SendKey / token / 机器人 key |

4. **启用 Actions**：Settings → Actions → General → 选 Allow all actions
5. **手动跑一次**：Actions → 贴吧签到 → Run workflow，确认成功
6. 之后每天**北京时间 06:30** 自动执行

> Fork 来的仓库默认不跑定时任务，必须手动触发过至少一次，或提交一次 commit。

## 推送配置

| PUSH_TYPE | PUSH_KEY 填什么 | 从哪拿 |
|---|---|---|
| `serverchan` | SendKey（`SCT` 开头） | [sct.ftqq.com](https://sct.ftqq.com) |
| `pushplus` | token | [pushplus.plus](https://www.pushplus.plus) |
| `wecom` | 企业微信群机器人 webhook 里 `key=` 后面那段 | 群设置 → 群机器人 |

不配就只在 Actions 日志里输出结果。

## 输出示例

```
[06:31:02] ① 校验登录态
[06:31:05] ② 拉取关注贴吧列表
[06:31:06]    列表第 1 页: 200 条，新增 200，累计 200
...
[06:31:10]    列表第 6 页: 93 条，新增 93，累计 1093
[06:31:10]    共 1093 个贴吧待签到
[06:31:10] ③ 开始签到
[06:31:40]    进度 50/1093 | 成功 48 已签 2 屏蔽 0 失败 0
...
[07:05:22] 完成 | 共 1093 个 | 成功 980 | 已签 110 | 屏蔽 3 | 失败 0
[07:05:22] 成功率 99.7% | 耗时 33分12秒
```

## 可选变量

在仓库 Settings → Secrets and variables → Actions → **Variables** 里加：

- `MAX_FORUMS`：只签前 N 个吧，留空或 0 表示全量

## 注意事项

**BDUSS 等同于账号密码。** 它能发帖、发私信、读取你的全部历史发言，有效期长达数年，只有退出登录或改密码才会失效。

- 只放在 GitHub Secrets 里，**不要写进代码、不要提交、不要发给任何人**
- 一旦泄露，立刻到贴吧 App / 网页退出登录，让 BDUSS 失效
- Public 仓库的 Secrets 对 fork 的 PR 不可见，但仍建议不要在代码里打印它

**风控风险。** 客户端接口批量签到有概率导致 App 无法点赞，极端情况会封号。本脚本把请求间隔控制在 0.45~0.95 秒、每 30 个休息 2~4 秒，属于比较保守的节奏，但风险无法完全消除。

**定时不精确。** GitHub Actions 的 cron 在高峰期可能延迟 10~60 分钟，这是平台行为，无法规避。

**60 天自动禁用。** 仓库 60 天无活动，GitHub 会停用定时工作流。本仓库的 `keepalive` job 每次运行都会通过 API 重新启用，不会产生垃圾 commit。

## 文件说明

| 文件 | 用途 |
|---|---|
| `tieba_sign.py` | 主脚本 |
| `.github/workflows/tieba.yml` | Actions 定时任务 + 保活 |
| `requirements.txt` | 依赖 |
