# GitHub Actions 版钉钉每日安全提示

这个版本把“定时触发”放到 GitHub Actions：

- 不依赖你的电脑开机；
- 不依赖手机后台常驻；
- 每天按北京时间 `07:00` 触发；
- 可在 GitHub 页面手动触发一次测试；
- Webhook 和加签密钥放在 GitHub Actions Secrets，不写入代码；
- 图片库放在仓库中，公开仓库可以直接使用 GitHub Raw 地址显示图片。

当前仓库截图显示的是 `vanish2000-AI/HomeAppt-master`。建议把本目录中的内容复制到该仓库根目录；不要把 `DINGTALK_WEBHOOK_URL` 或加签密钥写进仓库文件。

## 需要放进仓库的文件

```text
.github/
└─ workflows/
   └─ dingtalk-daily-safety-tip.yml

dingtalk/
├─ config.json
├─ image-library.json
├─ send_dingtalk_safety_tip.py
└─ images/
   └─ 微信图片_20261002003042_69_63.png
```

## 配置 GitHub Secrets

在仓库进入：

`Settings` → `Secrets and variables` → `Actions` → `New repository secret`

新增：

| Name | Value |
|---|---|
| `DINGTALK_WEBHOOK_URL` | 你的钉钉机器人完整 Webhook |
| `DINGTALK_SECRET` | 加签密钥；未启用加签时可以不创建这个 Secret |

Webhook 和密钥只放在 Secrets 中，不要放入 `config.json`、`image-library.json` 或工作流文件。

## 时间

工作流使用：

```yaml
cron: '0 23 * * *'
```

GitHub Actions 的 cron 按 UTC 解释，因此 `23:00 UTC` 对应北京时间每天 `07:00`。

如果你以后要改成北京时间 08:30，应改为：

```yaml
cron: '30 0 * * *'
```

## 手动测试

上传工作流后，进入仓库的 `Actions` 页面，选择 **DingTalk daily safety tip**，点击 **Run workflow**。

这会真实发送一条钉钉消息。首次测试前确认 Webhook、关键词和 `@所有人` 设置。

如果只想在本地检查随机图片和 JSON，不发消息，可以在仓库根目录执行：

```powershell
$env:DINGTALK_CONFIG_PATH = "dingtalk/config.json"
python .\dingtalk\send_dingtalk_safety_tip.py --dry-run
```

## 图片显示

工作流会从 `dingtalk/image-library.json` 的 `enabled=true` 条目中随机抽取一张图片。

当前图片的 `publicUrl` 留空，工作流会自动把它拼成：

```text
https://raw.githubusercontent.com/<仓库>/<分支>/dingtalk/images/<图片文件>
```

因此图片文件必须提交到**公开仓库**，钉钉才能读取 Raw 地址。如果仓库是私有仓库，图片地址无法被钉钉访问，需要把 `publicUrl` 改成其他公网图片地址，或者在仓库 Variables 中增加 `DINGTALK_IMAGE_BASE_URL` 并调整工作流。

以后增加图片：

1. 把图片放进 `dingtalk/images/`；
2. 在 `dingtalk/image-library.json` 增加条目；
3. 设置 `enabled` 为 `true`；
4. 如果使用 GitHub Raw，`publicUrl` 可以留空，脚本会自动生成；
5. 提交后无需修改定时任务。

## 运行边界

- GitHub Actions 定时任务不是严格实时系统，高峰期可能出现少量延迟；
- `workflow_dispatch` 手动运行会真实发消息；
- 仓库可以公开图片，但不要公开 Webhook、Secret 或其他敏感配置；
- 本方案不再要求你的电脑或手机保持开机。
