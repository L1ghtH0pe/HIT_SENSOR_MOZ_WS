# 6字节通信协议说明

## 协议变更

从 4 字节帧升级到 6 字节帧，支持动态配置下位机的 `target` 和 `range` 参数。

---

## 发送帧格式（上位机 → 下位机）

**帧结构（6字节）：**

```
[0xA5, flag, target, range, crc_lo, crc_hi]
```

| 字节 | 名称 | 说明 |
|------|------|------|
| 0 | header | 固定为 `0xA5` |
| 1 | flag | 当前力度等级 (0-255) |
| 2 | target | 目标值 (1-255)，下位机以此为中心计算目标区间 |
| 3 | range | 目标范围 (0-127)，目标区间为 `[target-range, target+range]` |
| 4 | crc_lo | CRC16 低字节 |
| 5 | crc_hi | CRC16 高字节 |

**CRC16 计算范围：** 前 4 个字节 `[0xA5, flag, target, range]`

**默认值：**
- `target = 127`
- `range = 20`

---

## 接收帧格式（下位机 → 上位机）

**帧结构（6字节）：**

```
[0x5A, flag, target, range, crc_lo, crc_hi]
```

| 字节 | 名称 | 说明 |
|------|------|------|
| 0 | header | 固定为 `0x5A` |
| 1 | flag | 当前力度等级（回传） |
| 2 | target | 目标值（回传） |
| 3 | range | 目标范围（回传） |
| 4 | crc_lo | CRC16 低字节 |
| 5 | crc_hi | CRC16 高字节 |

**CRC16 计算范围：** 前 4 个字节 `[0x5A, flag, target, range]`

---

## 参数说明

### target（目标值）

下位机会把 `target` 作为 LED 变绿和蜂鸣开始提示的目标点。

- 范围：1-255（0 被下位机当作 1 处理，建议直接限制 1-255）
- 默认：127

### range（目标范围）

下位机用它计算目标区间：

```
目标下限 = max(0, target - range)
目标上限 = min(255, target + range)
```

- 范围：0-127
- 默认：20

**示例**：
- `target=127, range=20` → 目标区间 `107-147`
- `target=100, range=30` → 目标区间 `70-130`

---

## 上位机使用方式

### 启动参数

```bash
# 默认 target=127, range=20
./start_all.sh

# 自定义 target 和 range
TARGET=150 RANGE=30 ./start_all.sh

# 配合其他参数
HAND=right TARGET=100 RANGE=25 ./start_all.sh
```

### ROS2 参数

```bash
python3 tactile_feedback.py --ros-args \
  -p target:=150 \
  -p range:=30
```

---

## 发送逻辑

上位机每次发送力度时，会把当前的 `target` 和 `range` 一起发送（即使它们没变化）。

这样下位机能随时同步当前配置，支持运行时动态调整。

---

## CRC16 算法

使用 CRC-16/MCRF4XX：
- 初始值：`0xFFFF`
- 多项式：`0x8408`（反向）
- 结果字节序：**低字节在前，高字节在后**

代码实现见 `tactile_feedback.py` 的 `crc16_mcrf4xx()` 函数。

---

## 测试

运行协议测试：

```bash
source /opt/ros/foxy/setup.bash
source ~/ros2_ws/install/setup.bash
python3 test_protocol_6byte.py
```

预期输出：
```
✓ 所有测试通过，6字节协议正确实现
```

---

## 示例帧

### 发送示例

`flag=100, target=127, range=20`：

```
a5 64 7f 14 ce 8c
```

解析：
- `0xA5` — 帧头
- `0x64` (100) — flag
- `0x7F` (127) — target
- `0x14` (20) — range
- `0xCE` `0x8C` — CRC16 = 0x8CCE

### 接收示例

下位机回传 `flag=128, target=127, range=20`：

```
5a 80 7f 14 dc 23
```

解析：
- `0x5A` — 帧头
- `0x80` (128) — flag
- `0x7F` (127) — target
- `0x14` (20) — range
- `0xDC` `0x23` — CRC16 = 0x23DC

---

## 兼容性说明

**旧版 4 字节协议（已废弃）：**

```
发送: [0xA5, flag, crc_lo, crc_hi]
接收: [0x5A, flag, crc_lo, crc_hi]
```

**新版 6 字节协议：**

```
发送: [0xA5, flag, target, range, crc_lo, crc_hi]
接收: [0x5A, flag, target, range, crc_lo, crc_hi]
```

上下位机必须同时升级，协议不兼容旧版。
