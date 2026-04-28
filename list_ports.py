"""
Windows 串口扫描工具
列出所有可用 COM 口并尝试识别华威科触觉传感器
"""

import serial
import serial.tools.list_ports
import time
import struct
from typing import List, Optional


def list_all_ports():
    """列出所有可用的串口"""
    ports = serial.tools.list_ports.comports()

    if not ports:
        print("未检测到任何串口设备")
        return []

    print(f"检测到 {len(ports)} 个串口设备:\n")
    print(f"{'端口':<10} {'描述':<40} {'硬件ID':<30}")
    print("-" * 85)

    for port in ports:
        print(f"{port.device:<10} {port.description:<40} {port.hwid:<30}")

    return [port.device for port in ports]


def calculate_checksum(payload: bytes) -> int:
    """计算负载校验和 (CRC16/Modbus over payload, seed=0x0000)"""
    crc = 0x0000
    for byte in payload:
        crc ^= byte
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc


def try_read_device_info(port: str, baudrate: int,
                         device_id: int = 1, channel: int = 2) -> Optional[dict]:
    """尝试读取设备信息"""
    try:
        ser = serial.Serial(
            port=port,
            baudrate=baudrate,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=0.5
        )
        time.sleep(0.1)

        id_chan = (device_id << 4) | (channel & 0x0F)
        payload = bytes([0x01])
        checksum = calculate_checksum(payload)

        frame = b'\x3C\x3C'
        frame += bytes([id_chan, 0x69])
        frame += struct.pack('<H', len(payload))
        frame += payload
        frame += struct.pack('<H', checksum)
        frame += b'\x3E\x3E'

        ser.write(frame)
        time.sleep(0.1)

        response = ser.read(512)
        ser.close()

        if len(response) >= 11:
            if response[:2] == b'\x3C\x3C' and response[-2:] == b'\x3E\x3E':
                return {
                    'port': port,
                    'baudrate': baudrate,
                    'device_id': device_id,
                    'channel': channel,
                    'response_length': len(response)
                }

        return None

    except Exception:
        return None


def scan_for_huaweike_sensor(ports: List[str],
                             baudrates: List[int] = None) -> List[dict]:
    """扫描华威科传感器"""
    if baudrates is None:
        baudrates = [921600, 115200, 57600, 38400, 19200, 9600]

    print("\n开始扫描华威科传感器...")
    print(f"扫描端口: {ports}")
    print(f"尝试波特率: {baudrates}\n")

    found_devices = []
    total_attempts = len(ports) * len(baudrates)
    current_attempt = 0

    for port in ports:
        for baudrate in baudrates:
            current_attempt += 1
            print(f"[{current_attempt}/{total_attempts}] 测试 {port} @ {baudrate} bps...", end='')

            result = try_read_device_info(port, baudrate)
            if result:
                print(" ✓ 找到设备!")
                found_devices.append(result)
                break
            else:
                print(" ✗")

    return found_devices


def main():
    print("=" * 85)
    print("华威科触觉传感器串口扫描工具")
    print("=" * 85)
    print()

    available_ports = list_all_ports()

    if not available_ports:
        return

    print("\n" + "=" * 85)

    # found_devices = scan_for_huaweike_sensor(available_ports)

    # print("\n" + "=" * 85)
    # print("扫描结果:")
    # print("=" * 85)

    # if found_devices:
    #     print(f"\n找到 {len(found_devices)} 个华威科传感器:\n")
    #     for i, device in enumerate(found_devices, 1):
    #         print(f"设备 {i}:")
    #         print(f"  端口: {device['port']}")
    #         print(f"  波特率: {device['baudrate']}")
    #         print(f"  设备ID: {device['device_id']}")
    #         print(f"  通道: {device['channel']}")
    #         print(f"  响应长度: {device['response_length']} 字节")
    #         print()
    #         print(f"连接命令:")
    #         print(f"  python sensor_cli.py -p {device['port']} -b {device['baudrate']} test")
    #         print()
    # else:
    #     print("\n未找到华威科传感器")
    #     print("\n可能的原因:")
    #     print("  1. 设备未连接或未上电")
    #     print("  2. 驱动程序未正确安装")
    #     print("  3. 设备使用了非标准波特率")
    #     print("  4. 串口被其他程序占用")
    #     print("\n建议:")
    #     print("  1. 检查设备连接和电源")
    #     print("  2. 在设备管理器中确认串口设备")
    #     print("  3. 查看设备文档确认波特率配置")


if __name__ == '__main__':
    main()
