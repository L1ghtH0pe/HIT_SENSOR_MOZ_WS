#!/bin/bash
# 停止 HIT 触觉反馈系统所有节点

R='\033[0;31m'; G='\033[0;32m'; Y='\033[0;33m'; N='\033[0m'

echo -e "${Y}停止 HIT 触觉系统...${N}"
KILLED=0
for proc in hit_tactile_publisher tactile_feedback hit_tactile_subscriber; do
    if pgrep -f "$proc" > /dev/null; then
        pkill -f "$proc"
        echo -e "${G}  ✓ 已停止 $proc${N}"
        KILLED=$((KILLED + 1))
    fi
done

if [ $KILLED -eq 0 ]; then
    echo -e "${Y}  没有正在运行的节点${N}"
else
    sleep 1
    REMAIN=$(pgrep -af "hit_tactile_publisher\|tactile_feedback\|hit_tactile_subscriber" | grep -v "pgrep" | wc -l)
    if [ "$REMAIN" -gt 0 ]; then
        echo -e "${R}  ⚠ 仍有 $REMAIN 个进程,强制结束${N}"
        pkill -9 -f "hit_tactile_publisher|tactile_feedback|hit_tactile_subscriber"
    fi
    echo -e "${G}全部停止${N}"
fi
