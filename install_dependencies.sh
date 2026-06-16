#!/bin/bash
# HIT触觉传感器项目依赖安装脚本

echo "=== 安装Python依赖 ==="

# 安装pyserial
echo "1. 安装 pyserial (串口通信库)..."
sudo apt-get update
sudo apt-get install -y python3-serial

# 安装其他可能缺失的依赖
echo "2. 检查并安装其他依赖..."
sudo apt-get install -y python3-matplotlib python3-numpy python3-pyqt5

echo ""
echo "=== 依赖安装完成 ==="
echo ""
echo "接下来你可以运行："
echo "  python3 update_visual_tactile.py /dev/ttyUSB0 foot 50"
echo ""
