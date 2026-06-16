#!/usr/bin/env python3
"""
STM32 写入测试 - 诊断 6 字节协议下位机是否能正常接收
直接往 /dev/ttyACM0 写 6 字节帧，观察是否 Write timeout。

用法：
    ./stop_all.sh      # 先停掉系统，释放 ttyACM0
    python3 test_stm32_write.py
"""

import serial
import time

# CRC-16/MCRF4XX（与下位机一致，初始值 0xFFFF）
_CRC_TABLE = []
for _i in range(256):
    _c = _i
    for _ in range(8):
        _c = (_c >> 1) ^ 0x8408 if _c & 1 else _c >> 1
    _CRC_TABLE.append(_c & 0xFFFF)


def crc16(data, init=0xFFFF):
    crc = init
    for b in data:
        crc = (crc >> 8) ^ _CRC_TABLE[(crc ^ b) & 0xFF]
    return crc & 0xFFFF


def build_frame(flag, target, range_val):
    """6字节帧: [0xA5, flag, target, range, crc_lo, crc_hi]"""
    payload = bytes((0xA5, flag & 0xFF, target & 0xFF, range_val & 0xFF))
    crc = crc16(payload)
    return payload + bytes((crc & 0xFF, (crc >> 8) & 0xFF))


PORT = '/dev/ttyACM0'

print("=" * 60)
print("STM32 6字节协议写入测试")
print("=" * 60)

print(f"\n打开 {PORT} ...")
try:
    ser = serial.Serial(PORT, 115200, timeout=0.2, write_timeout=1.0)
except Exception as e:
    print(f"✗ 打开失败: {e}")
    print("  → 检查权限 (sudo chmod 666 /dev/ttyACM0) 或设备是否存在")
    raise SystemExit(1)

# 有些 STM32 CDC 固件需要 DTR 信号才会接收数据
ser.setDTR(True)
ser.setRTS(True)
time.sleep(0.3)
print("✓ 端口已打开，DTR/RTS 已置位\n")

# ---------- 测试1：单帧写入是否超时 ----------
print("【测试1】写入5帧固定值 (flag=100, target=127, range=20)")
ok_count = 0
for i in range(5):
    frame = build_frame(100, 127, 20)
    try:
        n = ser.write(frame)
        ser.flush()
        ok_count += 1
        print(f"  帧{i}: ✓ 写入 {n} 字节  {frame.hex(' ')}")
    except serial.SerialTimeoutException:
        print(f"  帧{i}: ✗ Write timeout（下位机没取走USB数据）")
    except Exception as e:
        print(f"  帧{i}: ✗ {e}")
    time.sleep(0.5)

print(f"\n  写入成功率: {ok_count}/5")

if ok_count == 0:
    print("  → 全部 Write timeout：下位机固件USB接收端有问题")
    print("    检查固件 CDC_Receive_FS 回调 / HIT_DataReceive 是否")
    print("    正确处理6字节并重新arm接收端点")
    ser.close()
    raise SystemExit(0)

# ---------- 测试2：循环不同力度，观察LED变色 ----------
print("\n【测试2】循环发送不同 force，观察LED颜色变化")
print("  预期: 红(弱) -> 黄 -> 绿(目标127) -> 黄 -> 红(强)")
print("  按 Ctrl+C 停止\n")

try:
    while True:
        for f in [40, 90, 127, 160, 220, 255]:
            frame = build_frame(f, 127, 20)
            try:
                ser.write(frame)
                ser.flush()
                print(f"  发送 force={f:3d}  {frame.hex(' ')}")
            except Exception as e:
                print(f"  发送 force={f:3d} 失败: {e}")
            time.sleep(1.5)
except KeyboardInterrupt:
    print("\n停止，发送复位帧 (force=0)")
    try:
        ser.write(build_frame(0, 127, 20))
        ser.flush()
    except Exception:
        pass
finally:
    ser.close()
    print("端口已关闭")
