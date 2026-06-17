#!/bin/bash
# HIT 触觉反馈系统一键启动脚本
# 自动检测设备、修正端口配置、启动 publisher + feedback + 可视化

WS_DIR="$(cd "$(dirname "$0")" && pwd)"
# 自动检测 ROS2 版本（优先级：环境变量 > 已source的版本 > 自动扫描 /opt/ros）
if [ -n "$ROS_DISTRO_OVERRIDE" ] && [ -f "/opt/ros/$ROS_DISTRO_OVERRIDE/setup.bash" ]; then
    ROS_DISTRO_DETECTED="$ROS_DISTRO_OVERRIDE"
elif [ -n "$ROS_DISTRO" ] && [ -f "/opt/ros/$ROS_DISTRO/setup.bash" ]; then
    ROS_DISTRO_DETECTED="$ROS_DISTRO"
else
    # 按优先级扫描常见版本
    for d in jazzy humble foxy iron galactic; do
        if [ -f "/opt/ros/$d/setup.bash" ]; then
            ROS_DISTRO_DETECTED="$d"
            break
        fi
    done
fi
ROS_SETUP="/opt/ros/$ROS_DISTRO_DETECTED/setup.bash"
ROS2_WS_SETUP="$HOME/ros2_ws/install/setup.bash"
LOG_DIR="$WS_DIR/logs"
mkdir -p "$LOG_DIR"

R='\033[0;31m'; G='\033[0;32m'; Y='\033[0;33m'; B='\033[0;36m'; N='\033[0m'

echo -e "${B}========================================"
echo "  HIT 触觉声光反馈系统 - 一键启动"
echo -e "========================================${N}"

# ------- 1. 检测设备 -------
echo -e "\n${Y}[1/4] 检测硬件设备...${N}"
# 触觉传感器用 udev 固定符号链接 /dev/hit_tactile_*（避开 RM500Q 等无关 ttyUSB）
TACTILE_LINKS=$(ls /dev/hit_tactile_* 2>/dev/null)
TACTILE_COUNT=$(echo "$TACTILE_LINKS" | grep -c hit_tactile)
STM32_PORT=$(ls /dev/ttyACM* 2>/dev/null | head -1)

if [ -z "$TACTILE_LINKS" ]; then
    echo -e "${R}✗ 未检测到触觉传感器符号链接 (/dev/hit_tactile_*)${N}"
    echo "  请确认 udev 规则已安装，传感器已连接上电"
    echo "  （可运行 'ls -l /dev/hit_tactile_*' 检查）"
    exit 1
fi
if [ -z "$STM32_PORT" ]; then
    echo -e "${R}✗ 未检测到 STM32 下位机 (/dev/ttyACM*)${N}"
    echo "  请检查 STM32 USB 连接"
    exit 1
fi
echo -e "${G}  ✓ 触觉传感器: 检测到 $TACTILE_COUNT 个${N}"
echo "$TACTILE_LINKS" | sed 's/^/      /'
echo -e "${G}  ✓ STM32 下位机: $STM32_PORT${N}"

# 自动修正符号链接权限（设备重新插拔后权限会重置为 root）
for link in $TACTILE_LINKS; do
    if [ ! -w "$link" ]; then
        sudo chmod 666 "$link" 2>/dev/null && \
            echo -e "${Y}  已修正 $link 权限${N}"
    fi
done

# ------- 2. 修正 publisher 端口配置 -------
echo -e "\n${Y}[2/4] 检查端口配置...${N}"
# 注释掉自动修正逻辑，因为我们有两个传感器使用不同端口
# CFG_PORT=$(grep -E "^\s*'port':" "$WS_DIR/hit_tactile_publisher.py" | grep -oE "/dev/ttyUSB[0-9]+" | head -1)
# if [ "$CFG_PORT" != "$TACTILE_PORT" ]; then
#     echo -e "${Y}  ⚠ publisher 配置 ($CFG_PORT) 与实际 ($TACTILE_PORT) 不符,自动修正${N}"
#     sed -i "/^[[:space:]]*#/!s|/dev/ttyUSB[0-9]\+|$TACTILE_PORT|g" "$WS_DIR/hit_tactile_publisher.py"
# fi
echo -e "${G}  ✓ 端口配置正确（已手动配置两个传感器）${N}"

# ------- 3. 检查 ROS 环境 -------
echo -e "\n${Y}[3/4] 检查 ROS2 环境...${N}"
[ ! -f "$ROS_SETUP" ] && { echo -e "${R}✗ 未检测到 ROS2 (在 /opt/ros 下未找到任何已知版本)${N}"; exit 1; }
if [ -f "$ROS2_WS_SETUP" ]; then
    echo -e "${G}  ✓ ROS2 $ROS_DISTRO_DETECTED + ros2_ws 就绪${N}"
else
    echo -e "${Y}  ⚠ ros2_ws 不存在，仅加载系统 ROS2 $ROS_DISTRO_DETECTED${N}"
fi

# ------- 4. 启动节点 -------
echo -e "\n${Y}[4/4] 启动节点...${N}"

PRESS_OFF="${PRESS_OFF:-30.0}"
PRESS_ON="${PRESS_ON:-300.0}"
METRIC="${METRIC:-sum}"
HAND="${HAND:-left}"  # left / right / both
FUSION="${FUSION:-maxsum}"  # maxsum: 各自sum取最大(默认) / sum: 逐点相加 / max: 逐点取最大
TARGET="${TARGET:-127}"  # 下位机目标值 (1-255)
RANGE="${RANGE:-43}"     # 下位机目标范围 (0-127)，默认±43对应force三段边界
SUM_MAX="${SUM_MAX:-1000}"  # sum归一化上限：sum [0,SUM_MAX] -> force [0,255]

# ROS2 jazzy 严格类型检查：DOUBLE 类型参数必须带小数点
# 用户传 SUM_MAX=500 这种整数会报 InvalidParameterTypeException
for var in PRESS_OFF PRESS_ON SUM_MAX; do
    val="${!var}"
    case "$val" in
      *.*) ;;                       # 已有小数点
      *)   eval "$var=\"${val}.0\"" ;;  # 自动补 .0
    esac
done

ENV_CMD="source $ROS_SETUP && [ -f $ROS2_WS_SETUP ] && source $ROS2_WS_SETUP; cd $WS_DIR"
HOLD_CMD='echo; echo "[已退出] 按回车关闭窗口"; read'

# 检测启动模式：有 DISPLAY 且有终端时用 gnome-terminal，否则用后台 nohup
MODE="gui"
if [ -z "$DISPLAY" ] || ! command -v gnome-terminal &>/dev/null; then
    MODE="background"
fi

start_gui() {
    local title="$1"; local cmd="$2"
    if ! gnome-terminal --title="$title" -- bash -c "$ENV_CMD && $cmd; $HOLD_CMD" 2>/dev/null; then
        return 1
    fi
    return 0
}

start_bg() {
    local name="$1"; local cmd="$2"
    nohup bash -c "$ENV_CMD && $cmd" > "$LOG_DIR/$name.log" 2>&1 &
    echo $! > "$LOG_DIR/$name.pid"
}

# Publisher
PUB_CMD="python3 hit_tactile_publisher.py"
if [ "$MODE" = "gui" ] && start_gui "HIT Publisher" "$PUB_CMD"; then
    echo -e "${G}  ✓ Publisher 启动 (终端窗口)${N}"
else
    start_bg "publisher" "$PUB_CMD"
    echo -e "${G}  ✓ Publisher 启动 (后台, 日志: $LOG_DIR/publisher.log)${N}"
fi
sleep 3

# Feedback
FB_CMD="python3 tactile_feedback.py --ros-args -p press_off:=$PRESS_OFF -p press_on:=$PRESS_ON -p metric:=$METRIC -p hand:=$HAND -p fusion:=$FUSION -p target:=$TARGET -p range:=$RANGE -p sum_max:=$SUM_MAX"
TARGET_LOW=$((TARGET > RANGE ? TARGET - RANGE : 0))
TARGET_HIGH=$((TARGET + RANGE > 255 ? 255 : TARGET + RANGE))
if [ "$MODE" = "gui" ] && start_gui "HIT Feedback" "$FB_CMD"; then
    echo -e "${G}  ✓ Feedback 启动 (hand=$HAND sum_max=$SUM_MAX STM32目标 $TARGET±$RANGE→$TARGET_LOW-$TARGET_HIGH)${N}"
else
    start_bg "feedback" "$FB_CMD"
    echo -e "${G}  ✓ Feedback 启动 (后台, hand=$HAND sum_max=$SUM_MAX STM32目标 $TARGET±$RANGE→$TARGET_LOW-$TARGET_HIGH)${N}"
fi
sleep 1

# 询问可视化(后台模式跳过,因为没法显示窗口)
if [ "$MODE" = "gui" ]; then
    echo
    read -p "是否启动热力图可视化? [Y/n] " viz
    if [[ ! "$viz" =~ ^[Nn]$ ]]; then
        VIS_CMD="python3 hit_tactile_subscriber.py"
        if start_gui "HIT Visualization" "$VIS_CMD"; then
            echo -e "${G}  ✓ 热力图启动${N}"
        else
            echo -e "${Y}  ⚠ 终端启动失败,跳过热力图(后台模式无法显示)${N}"
        fi
    fi
fi

echo -e "\n${B}========================================"
echo -e "${G}  系统启动完成!${B}"
echo -e "========================================${N}"

if [ "$MODE" = "background" ]; then
    echo -e "${Y}查看日志:${N}     tail -f $LOG_DIR/publisher.log"
    echo -e "${Y}             ${N} tail -f $LOG_DIR/feedback.log"
fi
echo -e "${Y}停止全部节点:${N} ./stop_all.sh  或  pkill -f 'hit_tactile|tactile_feedback'"
echo -e "${Y}调整阈值:${N}     PRESS_OFF=10 PRESS_ON=80 ./start_all.sh"
