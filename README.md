# qqshell_agent

一个极致轻量化的 QQ 机器人运维 Agent。用户在 QQ 里发送自然语言，DeepSeek 把它翻译成 shell 命令，并直接在宿主机上执行，再把结果回传到 QQ。

> ⚠️ **安全警告**
>
> 本项目会把大模型生成的内容直接交给 `subprocess.check_output(..., shell=True)` 执行，并且默认假设运行环境具有 root 权限。
> - 只在你完全信任的机器上运行，并且只授权给自己的 openid（`ADMIN_OPENID`）。
> - 不要把它部署在存有重要数据、生产环境或公网可直接访问的服务器上。
> - 大模型可能误解指令或被提示注入，生成破坏性命令（如 `rm -rf`）。建议先在虚拟机或容器中试用。

## 功能

- 接收 QQ 群 @ 消息、频道 @ 消息和私聊消息
- 调用 DeepSeek 生成回复或 shell 命令
- 命令输出截断后（最多 1500 字符）回传到 QQ
- 支持 `记住xxx` 指令，把内容写入本地长期记忆文件 `agent_memory.md`
- 每个用户保留最近 10 条对话作为短期上下文

## 环境要求

- Python 3.9+
- QQ 机器人应用（在 [QQ 开放平台](https://q.qq.com/) 创建）
- DeepSeek API Key

## 安装

### 方式一：一键脚本（Debian / Ubuntu）

```bash
git clone https://github.com/735560882/qqshell_agent-ultra-light-.git
cd qqshell_agent-ultra-light-
bash install.sh
```

脚本会安装 Python 环境、创建 `venv` 虚拟环境并安装依赖。首次运行时会生成 `.env`，填写后再次执行 `bash install.sh` 即可后台启动，日志输出到 `agent.log`。

### 方式二：手动安装

```bash
python -m venv .venv
source .venv/bin/activate        # Windows 使用 .venv\Scripts\activate
pip install -r requirements.txt
```

## 配置

复制配置模板并填写：

```bash
cp .env.example .env
```

| 变量 | 说明 |
| --- | --- |
| `APP_ID` | QQ 机器人的 AppID |
| `APP_SECRET` | QQ 机器人的 AppSecret |
| `DS_KEY` | DeepSeek API Key |
| `ADMIN_OPENID` | 允许使用机器人的用户 openid。**必须配置**，未配置时机器人会拒绝所有消息 |

`ADMIN_OPENID` 可以在机器人收到你的第一条消息后，从日志中获取。

## 运行

```bash
python agent.py
```

看到 `🚀 Agent 启动...` 即表示启动成功。

## 使用示例

- 直接发送需求，例如：`查看当前磁盘使用情况`
- 闲聊会直接回复文字
- 发送 `记住 服务器的备份目录在 /data/backup`，内容会追加到 `agent_memory.md`，之后每次对话都会作为背景信息

## 注意事项

- 代码中调用的模型名为 `deepseek-flash`，base URL 为 `https://api.deepseek.com/v1`。请根据 DeepSeek 官方文档确认你可用的模型名称后再使用。
- 长期记忆保存在 `agent_memory.md`，该文件已被 `.gitignore` 忽略，不会被提交到仓库。

## 许可证

本项目基于 [LICENSE](LICENSE) 文件中的协议发布。
