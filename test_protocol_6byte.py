#!/usr/bin/env python3
"""测试新的 6 字节通信协议"""

import sys
sys.path.insert(0, '/home/mxz/下载/HIT_sensor_ws')

from tactile_feedback import build_frame, parse_stm32_frame, crc16_mcrf4xx

def test_build_frame():
    print("=== 测试发送帧构造 ===")

    # 测试1：默认参数
    frame = build_frame(flag=100, target=127, range_val=20)
    print(f"flag=100, target=127, range=20")
    print(f"  帧: {frame.hex(' ')}")
    print(f"  长度: {len(frame)} 字节")
    assert len(frame) == 6, "帧长度应为 6 字节"
    assert frame[0] == 0xA5, "帧头应为 0xA5"
    assert frame[1] == 100, "flag 应为 100"
    assert frame[2] == 127, "target 应为 127"
    assert frame[3] == 20, "range 应为 20"

    # 手动验证 CRC
    payload = bytes([0xA5, 100, 127, 20])
    crc_calc = crc16_mcrf4xx(payload)
    crc_lo = crc_calc & 0xFF
    crc_hi = (crc_calc >> 8) & 0xFF
    assert frame[4] == crc_lo, f"CRC低字节应为 {crc_lo:02x}"
    assert frame[5] == crc_hi, f"CRC高字节应为 {crc_hi:02x}"
    print(f"  ✓ CRC16 校验通过: {crc_calc:04x}\n")

    # 测试2：边界值
    frame = build_frame(flag=255, target=1, range_val=127)
    print(f"flag=255, target=1, range=127")
    print(f"  帧: {frame.hex(' ')}")
    assert frame[1] == 255
    assert frame[2] == 1
    assert frame[3] == 127
    print(f"  ✓ 边界值测试通过\n")

def test_parse_frame():
    print("=== 测试接收帧解析 ===")

    # 构造一个合法的下位机回传帧
    payload = bytes([0x5A, 128, 127, 20])
    crc = crc16_mcrf4xx(payload)
    frame = payload + bytes([crc & 0xFF, (crc >> 8) & 0xFF])

    print(f"模拟下位机回传: {frame.hex(' ')}")
    result = parse_stm32_frame(frame)
    print(f"  解析结果: {result}")
    assert result is not None, "解析应成功"
    assert result['flag'] == 128
    assert result['target'] == 127
    assert result['range'] == 20
    print(f"  ✓ 解析成功\n")

    # 测试 CRC 错误
    bad_frame = bytes([0x5A, 128, 127, 20, 0xFF, 0xFF])
    result = parse_stm32_frame(bad_frame)
    print(f"错误CRC帧: {bad_frame.hex(' ')}")
    print(f"  解析结果: {result}")
    assert result is None, "CRC错误应返回 None"
    print(f"  ✓ CRC校验拒绝错误帧\n")

def test_protocol_compatibility():
    print("=== 测试协议兼容性 ===")

    # 上位机发送
    tx_frame = build_frame(flag=200, target=150, range_val=30)
    print(f"上位机发送: {tx_frame.hex(' ')}")

    # 模拟下位机回传相同参数
    rx_payload = bytes([0x5A, 200, 150, 30])
    rx_crc = crc16_mcrf4xx(rx_payload)
    rx_frame = rx_payload + bytes([rx_crc & 0xFF, (rx_crc >> 8) & 0xFF])
    print(f"下位机回传: {rx_frame.hex(' ')}")

    result = parse_stm32_frame(rx_frame)
    assert result['flag'] == 200
    assert result['target'] == 150
    assert result['range'] == 30
    print(f"  ✓ 双向通信参数一致\n")

if __name__ == '__main__':
    test_build_frame()
    test_parse_frame()
    test_protocol_compatibility()
    print("=" * 50)
    print("✓ 所有测试通过，6字节协议正确实现")
    print("=" * 50)
