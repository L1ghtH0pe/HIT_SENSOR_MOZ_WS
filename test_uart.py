"""
华威科传感器串口读写测试
COM6, 921600, 周期性发送查询报文并打印响应
"""

import serial
import struct
import time
from datetime import datetime


def crc16(data: bytes) -> int:
    """CRC16校验 (seed=0x0000, poly=0xA001)"""
    crc = 0x0000
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if (crc & 0x0001) else (crc >> 1)
    return crc


def parse_sensor_frame(response: bytes) -> dict:
    """解析传感器响应帧"""
    if len(response) < 11:
        return None

    if response[:2] != b'\x3C\x3C' or response[-2:] != b'\x3E\x3E':
        return None

    id_chan = response[2]
    flags = response[3]
    payload_len = struct.unpack('<H', response[4:6])[0]

    if len(response) < 10 + payload_len:
        return None

    payload = response[6:6+payload_len]
    recv_crc = struct.unpack('<H', response[6+payload_len:8+payload_len])[0]
    calc_crc = crc16(payload)

    if recv_crc != calc_crc:
        return None

    # 解析负载
    if len(payload) < 4:
        return None

    total_packets = payload[0]
    current_packet = payload[1]
    cols = payload[2]
    rows = payload[3]

    return {
        'device_id': id_chan >> 4,
        'channel': id_chan & 0x0F,
        'flags': flags,
        'total_packets': total_packets,
        'current_packet': current_packet,
        'cols': cols,
        'rows': rows,
        'sensor_count': rows * cols,
        'payload_len': payload_len,
        'crc_ok': True
    }


COMMAND = bytes([0x3C, 0x3C, 0x12, 0x69, 0x01, 0x00, 0x01, 0xC1, 0xC0, 0x3E, 0x3E])
# COMMAND = bytes([0x3C, 0x3C, 0x22, 0xAD, 0x01, 0x00, 0x01, 0xC1, 0xC0, 0x3E, 0x3E])


def main():
    # 配置参数
    SERIAL_PORT = '/dev/ttyUSB0'
    BAUD_RATE = 921600
    DEVICE_ID = 1
    CHANNEL = 2

    print('='*70)
    print('华威科触觉传感器串口测试')
    print('='*70)
    print(f'\n连接参数:')
    print(f'  串口: {SERIAL_PORT}')
    print(f'  波特率: {BAUD_RATE}')
    print(f'  设备ID: {DEVICE_ID}')
    print(f'  通道: {CHANNEL}')
    print()

    ser = serial.Serial(
        port=SERIAL_PORT,
        baudrate=BAUD_RATE,
        bytesize=serial.EIGHTBITS,
        parity=serial.PARITY_NONE,
        stopbits=serial.STOPBITS_ONE,
        timeout=0.01
    )

    print(f'✓ 连接成功')
    print(f'\n发送报文: {" ".join(f"{b:02X}" for b in COMMAND)}') 

    # 首次读取获取设备信息
    ser.write(COMMAND)
    time.sleep(0.05)
    response = ser.read(4096)

    if response:
        info = parse_sensor_frame(response)
        if info:
            print(f'\n设备信息:')
            print(f'  device_id: {info["device_id"]}')
            print(f'  channel: {info["channel"]}')
            print(f'  baud_rate: {BAUD_RATE}')
            print(f'  rows: {info["rows"]}')
            print(f'  cols: {info["cols"]}')
            print(f'  sensor_count: {info["sensor_count"]}')
            print(f'  total_packets: {info["total_packets"]}')
        else:
            print('\n⚠ 无法解析设备信息')
    else:
        print('\n⚠ 未收到响应')

    print(f'\n目标频率: 200 Hz (周期 5ms)')
    print('每帧打印原始报文')
    print('按 Ctrl+C 停止\n')

    frame_count = 0
    start_time = time.time()

    try:
        while True:
            loop_start = time.perf_counter()

            ser.write(COMMAND)
            response = ser.read(4096)

            if response:
                frame_count += 1
                ts = datetime.now().strftime('%H:%M:%S.%f')[:-3]
                hex_str = ' '.join(f'{b:02X}' for b in response)

                # 每帧打印原始报文
                print(f'[{ts}] #{frame_count:5d} | {hex_str}')
                print(f'{len(response)} bytes')

            # 精确控制到 5ms 周期 (200 Hz)
            elapsed = time.perf_counter() - loop_start
            sleep_time = 0.005 - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

    except KeyboardInterrupt:
        elapsed = time.time() - start_time
        actual_hz = frame_count / elapsed if elapsed > 0 else 0
        print(f'\n停止')
        print(f'统计: 共 {frame_count} 帧, 耗时 {elapsed:.2f}s, 平均频率 {actual_hz:.1f} Hz')
    finally:
        ser.close()
        print('串口已关闭')


if __name__ == '__main__':
    main()
