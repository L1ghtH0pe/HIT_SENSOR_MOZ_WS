# HIT触觉传感器 - 快速启动指南

## 🚀 最简单的启动方式

```bash
cd ~/下载/HIT_sensor_ws
python3 visualize_correct.py
```

**就这一条命令！** 然后用手按压传感器，观察热力图变化。

---

## ✅ 启动前检查（第一次运行需要）

### 1. 检查串口设备
```bash
ls /dev/ttyUSB*
# 应该看到：/dev/ttyUSB0
```

### 2. 检查串口权限
```bash
ls -l /dev/ttyUSB0
# 如果没有 rw 权限，执行：
sudo chmod 666 /dev/ttyUSB0
```

### 3. 检查Python依赖（只需要一次）
```bash
python3 -c "import serial; print('✓ pyserial OK')"
python3 -c "import numpy; print('✓ numpy OK')"
python3 -c "import matplotlib; print('✓ matplotlib OK')"
```

如果缺少依赖：
```bash
sudo apt-get install python3-serial python3-numpy python3-matplotlib
```

---

## 📊 其他运行方式

### 方式1：可视化热力图（推荐）
```bash
python3 visualize_correct.py
```
- 弹出matplotlib窗口
- 实时显示10x8热力图
- 按压传感器看变化

### 方式2：终端监控
```bash
python3 monitor_sensor.py
```
- 纯终端显示
- 实时显示总和、最大值
- 进度条显示压力大小

### 方式3：GUI上位机
```bash
python3 sensor_gui.py
```
- tkinter图形界面
- 可以手动发送指令
- 查看设备信息

### 方式4：调试模式
```bash
python3 debug_raw_data.py
```
- 查看原始二进制数据
- 诊断通信问题

---

## 🔧 常见问题

### 问题1：提示 "Permission denied"
```bash
sudo chmod 666 /dev/ttyUSB0
```

### 问题2：提示 "No module named 'serial'"
```bash
sudo apt-get install python3-serial
```

### 问题3：找不到 /dev/ttyUSB0
- 检查USB线是否连接
- 检查传感器是否上电
- 运行 `ls /dev/ttyUSB*` 查看实际串口名

### 问题4：热力图全是0
- 用手**用力**按压传感器
- 确保按压的是传感器表面
- 传感器可能需要预热几秒钟

---

## 📝 关键配置信息

| 参数 | 值 |
|------|-----|
| 串口 | `/dev/ttyUSB0` |
| 波特率 | 921600 |
| 设备ID | 0x03 |
| 通道 | 0x02 |
| 传感器点数 | 38 (2行x19列) |
| 映射后网格 | 10行x8列 |

---

## 🎯 快速测试流程

```bash
# 1. 进入目录
cd ~/下载/HIT_sensor_ws

# 2. 扫描设备（可选，验证传感器连接）
python3 scan_hit_tactile_id.py

# 3. 启动可视化
python3 visualize_correct.py

# 4. 按压传感器，观察热力图变化
```

---

## 💡 提示

- **第一次运行**：可能需要等待几秒钟初始化
- **按压力度**：需要一定力度才能看到明显变化
- **关闭程序**：关闭窗口或按 `Ctrl+C`
- **重新运行**：直接再次执行 `python3 visualize_correct.py`

---

## 📚 更多信息

- 完整项目文档：`PROJECT_GUIDE.md`
- 详细运行指南：`RUN_GUIDE.md`
- 依赖安装脚本：`install_dependencies.sh`

---

## 🆘 需要帮助？

如果遇到问题，按顺序尝试：

1. 检查串口权限：`ls -l /dev/ttyUSB0`
2. 扫描设备ID：`python3 scan_hit_tactile_id.py`
3. 查看原始数据：`python3 debug_raw_data.py`
4. 查看完整文档：`PROJECT_GUIDE.md`
