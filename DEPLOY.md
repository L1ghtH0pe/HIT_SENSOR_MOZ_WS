# 新机器部署指南

把这套触觉传感器上位机系统部署到一台新的 Ubuntu 机器上。

## 环境要求

- **Ubuntu 20.04**（ROS2 Foxy 官方支持的系统）
- 两个 HIT 触觉传感器（CH341 USB转串口）
- STM32 下位机（USB CDC，VID:PID=0483:5740）

---

## 部署步骤

### 1. 安装 ROS2 Foxy

```bash
sudo apt update && sudo apt install curl gnupg lsb-release -y
sudo curl -sSL https://raw.githubusercontent.com/ros/rosdistro/master/ros.key -o /usr/share/keyrings/ros-archive-keyring.gpg
echo "deb [signed-by=/usr/share/keyrings/ros-archive-keyring.gpg] http://packages.ros.org/ros2/ubuntu $(lsb_release -cs) main" | sudo tee /etc/apt/sources.list.d/ros2.list
sudo apt update
sudo apt install ros-foxy-ros-base python3-colcon-common-extensions -y
```

### 2. 安装 Python 依赖

```bash
sudo apt install python3-numpy python3-serial python3-pip -y
```

### 3. 部署自定义消息包 mc_core_interface（关键步骤）

这是自定义 ROS 消息包，定义了 `TactileState` 等消息，必须编译。

```bash
mkdir -p ~/ros2_ws/src
# 把 mc_core_interface 整个目录拷到 ~/ros2_ws/src/
# 源位置（旧机器）：~/ros2_ws/src/mc_core_interface
# 可用 scp / U盘 / git 传输

cd ~/ros2_ws
source /opt/ros/foxy/setup.bash
colcon build --packages-select mc_core_interface
```

验证编译成功：
```bash
ls ~/ros2_ws/install/mc_core_interface/  # 应该有内容
```

### 4. 获取上位机代码

```bash
git clone https://github.com/L1ghtH0pe/HIT-tactile-sensor.git
cd HIT-tactile-sensor
```

### 5. 配置串口权限

```bash
sudo usermod -aG dialout $USER
# 注销重新登录，或重启，才能生效
```

### 6. 启动

```bash
cd HIT-tactile-sensor
./start_all.sh
```

---

## 验证清单

启动后检查：

```bash
# 1. 传感器扫描（应看到两个 device_id）
python3 scan_hit_tactile_id.py

# 2. 进程是否在跑
ps aux | grep -E "hit_tactile_publisher|tactile_feedback" | grep python

# 3. 串口是否被占用（两个都占=两传感器都连上）
lsof /dev/ttyUSB0 /dev/ttyUSB1 | grep python
```

---

## 常见问题

| 报错 | 原因 | 解决 |
|------|------|------|
| `No module named 'mc_core_interface'` | 消息包没编译 | 重做步骤3 |
| `No module named 'rclpy'` | ROS环境没source | start_all.sh会自动source；手动跑需 `source /opt/ros/foxy/setup.bash` |
| `Permission denied: /dev/ttyUSB0` | 串口无权限 | 步骤5加入dialout组并重新登录 |
| `No module named 'numpy/serial'` | Python库缺失 | 重做步骤2 |
| 采集不到数据 | 端口对调 | 已有自动检测，跑 scan_hit_tactile_id.py 确认 |

---

## 路径说明（无需修改）

`start_all.sh` 已做可移植处理：
- 项目目录：自动取脚本所在位置（`dirname $0`），放哪都行
- ROS工作空间：用 `$HOME/ros2_ws`，自动适配用户名
- 唯一约定：`mc_core_interface` 必须编译在 `~/ros2_ws/install` 下

所以换机器、换用户名都不用改脚本，只要满足环境要求即可。

---

## 下位机（STM32）

下位机固件独立部署，与上位机无关：
- 工程目录：`HIT_BEEP_LED_MCU2.0`
- 用 Keil MDK 编译，ST-Link/DFU 烧录
- 颜色/音效逻辑见 `STM32_MODIFICATION_GUIDE.md`
