"""HIT触觉传感器通信协议编解码"""
from __future__ import annotations

import struct
from enum import IntEnum
from dataclasses import dataclass


class FrameMode(IntEnum):
    PEER = 0        # 平等模式
    MASTER_SLAVE = 1  # 主从模式


class OpType(IntEnum):
    PUT = 0b00
    GET = 0b01
    ACK = 0b11


HEAD = b'<<'   # 0x3C3C
TAIL = b'>>'   # 0x3E3E


@dataclass
class Frame:
    channel: int = 0
    flags: int = 0x00
    payload: bytes = b''
    device_id: int = 0  # 主从模式下使用，高4位

    @property
    def op_type(self) -> OpType:
        return OpType(self.flags & 0x03)

    @op_type.setter
    def op_type(self, value: OpType):
        self.flags = (self.flags & 0xFC) | (int(value) & 0x03)

    @property
    def request_id(self) -> int:
        return (self.flags >> 2) & 0x3F

    @request_id.setter
    def request_id(self, value: int):
        self.flags = (self.flags & 0x03) | ((value & 0x3F) << 2)


@dataclass
class SensorData:
    """传感器上行数据（ACK响应payload解析结果）"""
    total_packets: int
    current_packet: int
    rows: int
    cols: int
    data: list  # rows x cols 的二维列表，uint16 原始值

    def get_value(self, row: int, col: int) -> float:
        """获取指定位置的压力值"""
        if 0 <= row < self.rows and 0 <= col < self.cols:
            return self.data[row][col]
        raise IndexError(f"索引越界: ({row}, {col}), 有效范围: (0-{self.rows-1}, 0-{self.cols-1})")

    def to_flat_list(self) -> list:
        """展平为一维列表"""
        return [val for row in self.data for val in row]


class HIT_Tactile_Protocol:
    """HIT触觉传感器串口通信协议

    支持平等模式和主从模式的帧编解码。
    字节序: 小端优先 (little-endian)
    校验: 仅计算负载部分 (CRC16-Modbus)
    """

    def __init__(self, mode: FrameMode = FrameMode.PEER):
        self.mode = mode

    @staticmethod
    def _crc16(data: bytes) -> int:
        """CRC-16/ARC: poly=0x8005, init=0x0000, refin/refout=True"""
        crc = 0x0000
        for byte in data:
            crc ^= byte
            for _ in range(8):
                if crc & 0x0001:
                    crc = (crc >> 1) ^ 0xA001
                else:
                    crc >>= 1
        return crc & 0xFFFF

    def encode(self, frame: Frame) -> bytes:
        """将Frame编码为字节串"""
        buf = bytearray(HEAD)

        if self.mode == FrameMode.PEER:
            buf.append(frame.channel & 0xFF)
        else:
            id_channel = ((frame.device_id & 0x0F) << 4) | (frame.channel & 0x0F)
            buf.append(id_channel)

        buf.append(frame.flags & 0xFF)
        buf.extend(struct.pack('<H', len(frame.payload)))
        buf.extend(frame.payload)

        checksum = self._crc16(frame.payload)
        buf.extend(struct.pack('<H', checksum))
        buf.extend(TAIL)
        return bytes(buf)

    def decode(self, data: bytes) -> Frame:
        """从字节串解码为Frame，校验失败抛出ValueError"""
        if len(data) < 10:
            raise ValueError(f"帧长度不足: {len(data)} < 10")
        if data[:2] != HEAD:
            raise ValueError(f"帧头错误: {data[:2].hex()}")
        if data[-2:] != TAIL:
            raise ValueError(f"帧尾错误: {data[-2:].hex()}")

        frame = Frame()
        idx = 2

        if self.mode == FrameMode.PEER:
            frame.channel = data[idx]
        else:
            frame.device_id = (data[idx] >> 4) & 0x0F
            frame.channel = data[idx] & 0x0F
        idx += 1

        frame.flags = data[idx]
        idx += 1

        length = struct.unpack('<H', data[idx:idx+2])[0]
        idx += 2

        frame.payload = data[idx:idx+length]
        if len(frame.payload) != length:
            raise ValueError(f"负载长度不匹配: 期望{length}, 实际{len(frame.payload)}")
        idx += length

        checksum_recv = struct.unpack('<H', data[idx:idx+2])[0]
        checksum_calc = self._crc16(frame.payload)
        if checksum_recv != checksum_calc:
            raise ValueError(
                f"校验失败: 收到0x{checksum_recv:04X}, 计算0x{checksum_calc:04X}"
            )
        return frame

    def find_frames(self, stream: bytes) -> list[tuple[int, Frame]]:
        """从字节流中搜索并解析所有有效帧，返回 [(offset, Frame), ...]"""
        results = []
        i = 0
        while i < len(stream) - 9:
            if stream[i:i+2] != HEAD:
                i += 1
                continue
            if i + 6 > len(stream):
                break
            length = struct.unpack('<H', stream[i+4:i+6])[0]
            frame_len = 2 + 1 + 1 + 2 + length + 2 + 2
            if i + frame_len > len(stream):
                i += 1
                continue
            if stream[i+frame_len-2:i+frame_len] != TAIL:
                i += 1
                continue
            try:
                frame = self.decode(stream[i:i+frame_len])
                results.append((i, frame))
                i += frame_len
            except ValueError:
                i += 1
        return results

    @staticmethod
    def make_get_frame(channel: int, request_id: int = 0,
                       device_id: int = 0) -> Frame:
        """快捷构造GET请求帧"""
        f = Frame(channel=channel, device_id=device_id)
        f.op_type = OpType.GET
        f.request_id = request_id
        return f

    @staticmethod
    def make_ack_frame(channel: int, payload: bytes,
                       request_id: int = 0, device_id: int = 0) -> Frame:
        """快捷构造ACK响应帧"""
        f = Frame(channel=channel, payload=payload, device_id=device_id)
        f.op_type = OpType.ACK
        f.request_id = request_id
        return f

    @staticmethod
    def make_put_frame(channel: int, payload: bytes,
                       request_id: int = 0, device_id: int = 0) -> Frame:
        """快捷构造PUT帧"""
        f = Frame(channel=channel, payload=payload, device_id=device_id)
        f.op_type = OpType.PUT
        f.request_id = request_id
        return f

    @staticmethod
    def parse_sensor_data(payload: bytes) -> SensorData:
        """解析传感器上行数据payload

        Payload结构（参考visual_tactile.py）:
          - total_packets: 1B (总包数)
          - current_packet: 1B (当前包序号)
          - cols: 1B (列数)
          - rows: 1B (行数)
          - data: rows*cols*2B (uint16 LE, 原始值)

        Returns:
            SensorData: 解析后的传感器数据

        Raises:
            ValueError: payload格式错误
        """
        if len(payload) < 4:
            raise ValueError(f"payload长度不足: {len(payload)} < 4")

        total_packets = payload[0]
        current_packet = payload[1]
        cols = payload[2]
        rows = payload[3]

        expected_len = 4 + rows * cols * 2
        if len(payload) < expected_len:
            raise ValueError(
                f"payload数据不完整: 期望{expected_len}字节, 实际{len(payload)}字节"
            )

        # 解析传感器矩阵数据
        data = []
        offset = 4
        for _ in range(rows):
            row_data = []
            for _ in range(cols):
                raw_value = struct.unpack('<H', payload[offset:offset+2])[0]
                row_data.append(raw_value)
                offset += 2
            data.append(row_data)

        return SensorData(
            total_packets=total_packets,
            current_packet=current_packet,
            rows=rows,
            cols=cols,
            data=data
        )


if __name__ == '__main__':
    proto = HIT_Tactile_Protocol(FrameMode.PEER)

    # 测试1: 基本GET请求编码
    print("=== 测试1: GET请求编码 ===")
    frame = proto.make_get_frame(channel=0x12, request_id=0x1A)
    frame.payload = b'\x01'
    raw = proto.encode(frame)
    print(f"编码: {' '.join(f'{b:02X}' for b in raw)}")
    print(f"期望: 3C 3C 12 69 01 00 01 C1 C0 3E 3E")
    print()

    # 测试2: 解码验证
    print("=== 测试2: 帧解码 ===")
    decoded = proto.decode(raw)
    print(f"解码: ch=0x{decoded.channel:02X} op={decoded.op_type.name} "
          f"req_id=0x{decoded.request_id:02X} payload={decoded.payload.hex()}")
    print()

    # 测试3: 传感器数据解析
    print("=== 测试3: 传感器数据解析 ===")
    # 模拟传感器响应payload: 1包/共1包, 3列2行, 数据=[100, 200, 255, 150, 250, 128]
    sensor_payload = bytearray([
        0x01,  # total_packets
        0x01,  # current_packet
        0x03,  # cols
        0x02,  # rows
    ])
    # 添加传感器数据 (uint16 LE, 范围 0-255)
    for val in [100, 200, 255, 150, 250, 128]:
        sensor_payload.extend(struct.pack('<H', val))

    sensor_data = proto.parse_sensor_data(bytes(sensor_payload))
    print(f"包信息: {sensor_data.current_packet}/{sensor_data.total_packets}")
    print(f"矩阵尺寸: {sensor_data.rows}行 x {sensor_data.cols}列")
    print(f"压力值矩阵 (0-255):")
    for r, row in enumerate(sensor_data.data):
        print(f"  行{r}: {[int(v) for v in row]}")
    print(f"展平列表: {[int(v) for v in sensor_data.to_flat_list()]}")
    print()

    # 测试4: 主从模式
    print("=== 测试4: 主从模式 ===")
    proto_ms = HIT_Tactile_Protocol(FrameMode.MASTER_SLAVE)
    frame2 = proto_ms.make_put_frame(channel=0x02, payload=b'\x01',
                                     request_id=0x05, device_id=0x03)
    raw2 = proto_ms.encode(frame2)
    print(f"编码: {' '.join(f'{b:02X}' for b in raw2)}")
    decoded2 = proto_ms.decode(raw2)
    print(f"解码: id={decoded2.device_id} ch={decoded2.channel} "
          f"op={decoded2.op_type.name} payload={decoded2.payload.hex()}")
