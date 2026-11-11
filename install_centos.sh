#!/bin/bash
# CentOS / RHEL / Rocky / AlmaLinux 一键安装脚本
# 用法：bash install_centos.sh
# 如需指定 Python，例如 CentOS 8 上的 python3.9：PYTHON_BIN=python3.9 bash install_centos.sh
set -e
cd "$(dirname "$0")"

echo "=================================="
echo " 正在安装 Agent（CentOS / RHEL）"
echo "=================================="

# root 直接执行，否则使用 sudo
if [ "$(id -u)" -eq 0 ]; then SUDO=""; else SUDO="sudo"; fi

# CentOS 8 及以后用 dnf，CentOS 7 用 yum
if command -v dnf >/dev/null 2>&1; then PKG=dnf; else PKG=yum; fi

# 安装 Python 3 和 pip（venv 模块随 python3 包提供）
$SUDO $PKG install -y python3 python3-pip

PY="${PYTHON_BIN:-python3}"

# 检查 Python 版本（项目要求 3.9+）
if ! "$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)'; then
    echo "❌ 需要 Python 3.9 或更高版本，当前为：$("$PY" -V 2>&1)"
    echo "   CentOS 8 / Stream 可以尝试：$SUDO $PKG install -y python39"
    echo "   安装后用 PYTHON_BIN=python3.9 bash install_centos.sh 重新运行。"
    exit 1
fi

# 创建虚拟环境
"$PY" -m venv venv
source venv/bin/activate

# 安装依赖
pip install --upgrade pip -q
pip install -r requirements.txt

# 检查配置文件
if [ ! -f .env ]; then
    cp .env.example .env
    echo "⚠️ 安装完成！请先编辑 .env 文件填入你的密钥，然后再次执行 bash install_centos.sh 启动。"
else
    # 停止已有进程（匹配 "python agent.py" 和 "python -u agent.py"），避免重复启动
    pkill -f "python.*agent.py" 2>/dev/null || true
    sleep 1
    # -u：关闭输出缓冲，否则 OpenID 等信息不会立即写入 agent.log
    nohup venv/bin/python -u agent.py > agent.log 2>&1 &
    echo "✅ 配置已存在，后台启动成功！"
    echo "👉 实时日志查看：tail -f agent.log"
fi
