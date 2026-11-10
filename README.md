# Native Server Agent

一个基于 DeepSeek 和 QQ 官方 API 的极简、无沙盒、拥有长期记忆的服务器运维 Agent。

##  特性
- **极简原生**：拒绝臃肿的第三方框架，原生 Python 直连 DeepSeek API。
- **完全放权**：没有沙盒限制，直接调用宿主机 Shell 执行命令。
- **长期记忆**：通过本地 `agent_memory.md` 文件，永久记住你的工作区和习惯。
- **多端适配**：原生支持 QQ 频道、群聊、私聊。

>  **安全警告**
>
> 本项目会把大模型生成的内容直接交给 `subprocess.check_output(..., shell=True)` 执行，并且默认假设运行环境具有 root 权限。
> - 只在你完全信任的机器上运行，并且只授权给自己的 openid（`ADMIN_OPENID`）。
> - 不要把它部署在存有重要数据、生产环境或公网可直接访问的服务器上。
> - 大模型可能误解指令或被提示注入，生成破坏性命令（如 `rm -rf`）。建议先在虚拟机或容器中试用。

## 快速启动

1. **创建 QQ 机器人**：在 [QQ 开放平台](https://q.qq.com/) 创建机器人，记下 `AppID` 和 `AppSecret`。
2. **获取 DeepSeek Key**：在 [DeepSeek 开放平台](https://platform.deepseek.com/) 创建 API Key。
3. **安装并生成配置**（Debian / Ubuntu）：
   ```bash
   git clone https://github.com/735560882/qqshell_agent-ultra-light-.git
   cd qqshell_agent-ultra-light-
   bash install.sh
   ```
   首次运行会生成 `.env`，然后脚本会提示你编辑它。
4. **填写 `.env`**：填入 `APP_ID`、`APP_SECRET`、`DS_KEY`，`ADMIN_OPENID` 先留空；`ADMIN_TOTP_SECRET` 按“二次认证”部分生成后填入。
5. **获取你的 OpenID**：再次执行 `bash install.sh` 启动机器人，在群里或私聊中 @ 它发一条消息，然后查看日志：
   ```bash
   tail -f agent.log
   ```
   日志中会出现 `[AUTH] 拒绝未授权用户，OpenID: xxx`，把其中的 OpenID 复制到 `.env` 的 `ADMIN_OPENID`。
6. **重启生效**：再次执行 `bash install.sh`。然后私聊机器人发送 `#认证 动态码`，认证通过后即可下达指令。

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
| `ADMIN_TOTP_SECRET` | 动态码种子。**必须配置**，未配置时无法完成认证 |

## 二次认证（TOTP）

每次重启后或认证超过 30 分钟，都需要先通过动态码认证，才能使用机器人。

**1. 生成种子**（只需做一次）：

```bash
source venv/bin/activate
python -c "import pyotp; print(pyotp.random_base32())"
```

把输出的字符串填入 `.env` 的 `ADMIN_TOTP_SECRET`。

**2. 添加到验证器 App**（Google Authenticator、Microsoft Authenticator 等）：

```bash
python -c "import pyotp; print(pyotp.TOTP('你的种子').provisioning_uri(name='admin', issuer_name='qqshell_agent'))"
```

把输出的 `otpauth://` 链接转成二维码后扫描，或者直接在 App 里手动输入种子。

**3. 认证**：在 **私聊** 机器人中发送 `#认证 123456`（123456 为当前动态码）。认证成功后 30 分钟内有效。

- 同一个动态码只能使用一次，重复提交会被拒绝。
- 连续失败 5 次后锁定 15 分钟。

> 认证指令只能在私聊中使用。如果在群里发送，机器人会拒绝并提醒你。动态码每 30 秒变化一次，即使被看到，也很快失效。
>
> 注意：动态码种子保存在 `.env` 中，Agent 理论上能读取它。回复中出现的 `APP_SECRET`、`DS_KEY`、`ADMIN_TOTP_SECRET` 会被自动替换为 `***`，但这不能完全防止泄露。

`ADMIN_OPENID` 可以在机器人收到你的第一条消息后，从日志中获取。

## 运行

```bash
python agent.py
```

看到 `Agent 启动...` 即表示启动成功。

##  如何让它干活？

在 QQ 里 @ 你的机器人：

- **先认证（私聊）**：`#认证 123456`
- **植入记忆**：`@机器人 #记住 你的工作区在 /root/my_repo`
- **下达指令**：`@机器人 查一下现在的内存占用`
- **确认高危命令**：命令含 `rm -r`、`reboot`、`mkfs`、`dd if=` 等高危操作时，机器人会先暂停并列出命令，回复 `#确认` 执行（120 秒内有效），或回复 `#取消`。

未认证时，除认证指令外的所有消息都会被拒绝。

##  安全警告

本项目给予 Agent 极高的系统权限。请务必配置好 `ADMIN_OPENID`，绝对不要把带有 admin 权限的机器人暴露在公开的、不可信的群聊中。

## 注意事项

- 代码中调用的模型名为 `deepseek-flash`，base URL 为 `https://api.deepseek.com/v1`。请根据 DeepSeek 官方文档确认你可用的模型名称后再使用。
- 长期记忆保存在 `agent_memory.md`，该文件已被 `.gitignore` 忽略，不会被提交到仓库。

## 许可证

本项目基于 [MIT License](LICENSE) 开源，版权归 Fluxay 所有（2026）。
