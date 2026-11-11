#!/bin/bash
set -e
cd "$(dirname "$0")"

echo "=================================="
echo " 正在安装 Agent"
echo "=================================="

# 检查并安装环境（适用于 Debian / Ubuntu）
sudo apt update && sudo apt install python3-pip python3-venv -y

# 创建虚拟环境
python3 -m venv venv
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt

# 检查配置文件
if [ ! -f .env ]; then
    cp .env.example .env
    echo "⚠️ 安装完成！请先编辑 .env 文件填入你的密钥，然后执行："
    echo "source venv/bin/activate && nohup venv/bin/python -u agent.py > agent.log 2>&1 &"
else
    # 如果已有旧进程在运行，先停止，避免重复启动
    # 匹配 "python agent.py" 和 "python -u agent.py" 两种启动方式
    pkill -f "python.*agent.py" 2>/dev/null || true
    sleep 1
    # -u：关闭输出缓冲，否则 nohup 重定向到日志时 OpenID 等信息不会立即写入 agent.log
    nohup venv/bin/python -u agent.py > agent.log 2>&1 &
    echo "✅ 配置已存在，后台启动成功！"
    echo "👉 实时日志查看：tail -f agent.log"
fi
