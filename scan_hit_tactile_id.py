"""
华威科触觉传感器 ID 扫描工具
自动识别平台、扫描串口、匹配端口与设备 ID
"""

import sys
import os
import time
import struct
import serial
import serial.tools.list_ports
import subprocess


def crc16(data: bytes) -> int:
    crc = 0x0000
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if (crc & 0x0001) else (crc >> 1)
    return crc & 0xFFFF


def build_query_frame(device_id: int, channel: int = 0x02) -> bytes:
    """构造主从模式 GET 请求帧"""
    id_chan = ((device_id & 0x0F) << 4) | (channel & 0x0F)
    payload = b'\x01'
    flags = 0x01  # GET
    length = struct.pack('<H', len(payload))
    checksum = struct.pack('<H', crc16(payload))
    return b'\x3C\x3C' + bytes([id_chan, flags]) + length + payload + checksum + b'\x3E\x3E'


def has_valid_response(data: bytes) -> bool:
    """检查响应中是否包含有效帧"""
    i = 0
    while i < len(data) - 9:
        if data[i:i+2] != b'\x3C\x3C':
            i += 1
            continue
        if i + 6 > len(data):
            break
        plen = struct.unpack('<H', data[i+4:i+6])[0]
        frame_len = 2 + 1 + 1 + 2 + plen + 2 + 2
        if i + frame_len > len(data):
            i += 1
            continue
        if data[i+frame_len-2:i+frame_len] != b'\x3E\x3E':
            i += 1
            continue
        recv_payload = data[i+6:i+6+plen]
        recv_crc = struct.unpack('<H', data[i+6+plen:i+8+plen])[0]
        if recv_crc == crc16(recv_payload):
            return True
        i += 1
    return False


def ensure_port_permission(device: str) -> bool:
    """检查串口读写权限，不足时尝试通过 sudo chmod 赋予权限"""
    if os.access(device, os.R_OK | os.W_OK):
        return True

    print(f"  {device}: 权限不足，尝试 sudo chmod 666 ...")
    try:
        subprocess.run(['sudo', 'chmod', '666', device], check=True)
        print(f"  {device}: 权限已修复")
        return True
    except subprocess.CalledProcessError:
        print(f"  {device}: 权限修复失败，请手动执行: sudo chmod 666 {device}")
        return False


def scan_ports():
    """根据平台筛选串口"""
    ports = serial.tools.list_ports.comports()
    platform = sys.platform

    if platform == 'win32':
        filtered = [p for p in ports if 'CH340' in p.description.upper()]
        platform_name = 'Windows'
        filter_rule = 'CH340'
    else:
        filtered = [p for p in ports if 'ttyUSB' in p.device]
        platform_name = 'Linux'
        filter_rule = 'ttyUSB'

    print(f"平台: {platform_name}")
    print(f"筛选规则: {filter_rule}")
    print(f"匹配串口: {len(filtered)} 个\n")

    if platform != 'win32':
        filtered = [p for p in filtered if ensure_port_permission(p.device)]
        if len(filtered) == 0:
            print("所有串口权限不足，无法继续扫描")

    return filtered


def probe_port(port_info, id_range=range(1, 8), baudrate=921600):
    """探测单个串口上的设备 ID"""
    port = port_info.device
    found_ids = []

    try:
        ser = serial.Serial(port, baudrate, timeout=0.1)
        time.sleep(0.05)
    except Exception as e:
        print(f"  {port}: 打开失败 ({e})")
        return found_ids

    for dev_id in id_range:
        try:
            frame = build_query_frame(dev_id)
            ser.reset_input_buffer()
            ser.write(frame)
            time.sleep(0.02)
            resp = ser.read(4096)
            if resp and has_valid_response(resp):
                found_ids.append(dev_id)
                print(f"  {port}: ID 0x{dev_id:02X} -> 响应OK")
        except Exception:
            pass

    ser.close()
    return found_ids


def print_table(results):
    """输出 prettytable 风格的结果表"""
    if not results:
        print("\n未找到任何传感器设备")
        return

    max_port = max(len(r[0]) for r in results)
    pw = max(max_port, 4)

    hdr = f"| {'#':>3} | {'Port':<{pw}} | Dev ID |"
    sep = f"+{'-'*5}+{'-'*(pw+2)}+{'-'*8}+"

    print(f"\n{sep}")
    print(f"| {'#':>3} | {'Port':<{pw}} | Dev ID |")
    print(f"{sep}")
    for i, (port, dev_id) in enumerate(results, 1):
        print(f"| {i:>3} | {port:<{pw}} |   0x{dev_id:02X} |")
    print(sep)


def main():
    print("=" * 50)
    print("华威科触觉传感器 ID 扫描工具")
    print("=" * 50 + "\n")

    ports = scan_ports()
    if not ports:
        print("未找到匹配的串口设备")
        return

    results = []
    for p in ports:
        print(f"扫描 {p.device} ({p.description})...")
        ids = probe_port(p)
        for dev_id in ids:
            results.append((p.device, dev_id))

    print_table(results)


if __name__ == '__main__':
    main()
