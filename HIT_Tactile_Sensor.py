"""HIT触觉传感器类 - 支持多传感器并发读取"""
from __future__ import annotations

import serial
import threading
import time
import numpy as np
from typing import Optional, Callable
from HIT_Tactile_Protocol import (
    HIT_Tactile_Protocol,
    FrameMode,
    SensorData,
    Frame
)
from sensor_mapping import SensorMapping


class HIT_Tactile_Sensor:
    """HIT触觉传感器接口类

    支持单次读取和持续流式读取模式。
    线程安全，支持多个传感器实例并发运行。

    Args:
        port: 串口名称，如 'COM6'
        baudrate: 波特率，默认 921600
        channel: 通道号，默认 0x12
        mode: 帧模式，默认 PEER（平等模式）
        timeout: 串口读取超时（秒），默认 0.1
    """

    def __init__(
        self,
        port: str,
        baudrate: int = 921600,
        channel: int = 0x12,
        mode: FrameMode = FrameMode.PEER,
        timeout: float = 0.1,
        mapping: str = "foot"
    ):
        self.port = port
        self.baudrate = baudrate
        self.channel = channel
        self.timeout = timeout

        # 协议实例
        self.protocol = HIT_Tactile_Protocol(mode)

        # 传感器映射
        self.mapping = SensorMapping(mapping)
        self.grid_shape = self.mapping.get_grid_shape()

        # 串口对象
        self.ser: Optional[serial.Serial] = None
        self._lock = threading.Lock()  # 串口读写锁

        # 流式读取相关
        self._streaming = False
        self._stream_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._callback: Optional[Callable[[SensorData], None]] = None

        # 统计信息
        self.frame_count = 0
        self.error_count = 0

    def connect(self) -> bool:
        """连接串口

        Returns:
            bool: 连接成功返回 True，否则 False
        """
        if self.is_connected():
            return True

        try:
            self.ser = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=self.timeout
            )
            time.sleep(0.1)  # 等待串口稳定
            return True
        except Exception as e:
            print(f"[{self.port}] 连接失败: {e}")
            self.ser = None
            return False

    def disconnect(self):
        """断开串口连接"""
        if self._streaming:
            self.stop_streaming()

        with self._lock:
            if self.ser and self.ser.is_open:
                self.ser.close()
            self.ser = None

    def is_connected(self) -> bool:
        """检查串口是否已连接"""
        return self.ser is not None and self.ser.is_open

    def read_once(self, request_id: int = 0, use_lock: bool = True) -> Optional[SensorData]:
        """单次读取传感器数据

        Args:
            request_id: 请求ID，默认 0
            use_lock: 是否使用线程锁，单线程场景可设为 False 提升性能

        Returns:
            SensorData: 成功返回传感器数据，失败返回 None
        """
        if not self.is_connected():
            raise RuntimeError(f"[{self.port}] 串口未连接")

        def _read():
            response = None
            try:
                # 构造GET请求帧
                frame = self.protocol.make_get_frame(
                    channel=self.channel,
                    request_id=request_id
                )
                frame.payload = b'\x01'
                request_bytes = self.protocol.encode(frame)

                # 清空接收缓冲区，避免残留数据导致帧头/帧尾错位
                self.ser.reset_input_buffer()
                # 发送请求
                self.ser.write(request_bytes)

                # 先读取帧头(2) + channel(1) + flags(1) + length(2) = 6 字节
                header = self.ser.read(6)
                if len(header) < 6:
                    return None

                # 解析 payload 长度 (小端序)
                payload_len = header[4] | (header[5] << 8)
                # 完整帧 = header(6) + payload + checksum(2) + tail(2)
                remaining = payload_len + 4

                # 继续读取剩余数据
                body = self.ser.read(remaining)
                if len(body) < remaining:
                    # 数据不完整，尝试再读一次
                    body += self.ser.read(remaining - len(body))

                response = header + body
                if len(response) < 6 + remaining:
                    raise ValueError(f"帧不完整: 期望{6 + remaining}字节, 实际{len(response)}字节")

                # 解析响应帧
                response_frame = self.protocol.decode(response)
                sensor_data = self.protocol.parse_sensor_data(
                    response_frame.payload
                )
                self.frame_count += 1
                return sensor_data

            except Exception as e:
                self.error_count += 1
                print(f"[{self.port}] 读取失败: {e}")
                if response:
                    print(f"[{self.port}] 原始报文 ({len(response)} bytes): {response.hex()}")
                return None

        if use_lock:
            with self._lock:
                return _read()
        else:
            return _read()

    def read_mapped(self, request_id: int = 0, use_lock: bool = True) -> Optional[np.ndarray]:
        """读取传感器数据并映射为面阵矩阵

        Returns:
            np.ndarray: 映射后的网格矩阵（如足底10x8），无传感器位置为 0
        """
        data = self.read_once(request_id, use_lock=use_lock)
        if data is None:
            return None

        flat = np.array(data.to_flat_list(), dtype=np.float32)
        return self.mapping.map_data_to_grid(flat)

    def read_and_print(self, request_id: int = 0) -> Optional[np.ndarray]:
        """读取传感器数据，映射为面阵矩阵，并打印到终端

        Returns:
            np.ndarray: 映射后的网格矩阵，同时打印到终端
        """
        grid = self.read_mapped(request_id)
        if grid is None:
            print(f"[{self.port}] 读取失败")
            return None

        # 打印矩阵
        rows, cols = grid.shape
        print(f"\n[{self.port}] 触觉矩阵 ({rows}x{cols}):")

        # 列标题
        col_header = "     " + "".join(f"  C{c+1:02d}" for c in range(cols))
        print(col_header)
        print("     " + "-----" * cols)

        # 数据行
        for r in range(rows):
            row_vals = []
            for c in range(cols):
                val = grid[r, c]
                row_vals.append(f"{val:5.1f}")
            row_str = " | ".join(row_vals)
            print(f"R{r+1:02d} | {row_str}")

        print(f"\n有效传感器: {self.mapping.get_sensor_count()}/{rows*cols}")
        return grid

    def start_streaming(
        self,
        callback: Callable[[SensorData], None],
        interval: float = 0.05
    ):
        """启动流式读取模式（后台线程持续采集）

        Args:
            callback: 数据回调函数，接收 SensorData 参数
            interval: 采集间隔（秒），默认 0.05（20Hz）
        """
        if self._streaming:
            print(f"[{self.port}] 流式读取已在运行")
            return

        if not self.is_connected():
            raise RuntimeError(f"[{self.port}] 串口未连接")

        self._callback = callback
        self._stop_event.clear()
        self._streaming = True

        self._stream_thread = threading.Thread(
            target=self._stream_worker,
            args=(interval,),
            daemon=True,
            name=f"Sensor-{self.port}"
        )
        self._stream_thread.start()
        print(f"[{self.port}] 流式读取已启动")

    def stop_streaming(self):
        """停止流式读取"""
        if not self._streaming:
            return

        self._stop_event.set()
        if self._stream_thread:
            self._stream_thread.join(timeout=2.0)
        self._streaming = False
        print(f"[{self.port}] 流式读取已停止")

    def _stream_worker(self, interval: float):
        """流式读取工作线程"""
        request_id = 0
        while not self._stop_event.is_set():
            try:
                data = self.read_once(request_id)
                if data and self._callback:
                    self._callback(data)
                request_id = (request_id + 1) % 64
            except Exception as e:
                print(f"[{self.port}] 流式读取异常: {e}")

            time.sleep(interval)

    def get_stats(self) -> dict:
        """获取统计信息"""
        return {
            'port': self.port,
            'connected': self.is_connected(),
            'streaming': self._streaming,
            'frame_count': self.frame_count,
            'error_count': self.error_count,
            'error_rate': (
                self.error_count / self.frame_count
                if self.frame_count > 0 else 0
            )
        }

    def __enter__(self):
        """上下文管理器支持"""
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器支持"""
        self.disconnect()

    def __repr__(self):
        status = "connected" if self.is_connected() else "disconnected"
        return f"<HIT_Tactile_Sensor port={self.port} status={status}>"


class MultiSensorManager:
    """多传感器管理器

    统一管理多个 HIT_Tactile_Sensor 实例的生命周期和数据采集。

    Args:
        ports: 串口列表，如 ['COM3', 'COM6']
        baudrate: 统一波特率，默认 921600
        channel: 统一通道号，默认 0x12
    """

    def __init__(
        self,
        ports: list[str],
        baudrate: int = 921600,
        channel: int = 0x12,
        mapping: str = "foot"
    ):
        self.sensors: dict[str, HIT_Tactile_Sensor] = {}
        for port in ports:
            self.sensors[port] = HIT_Tactile_Sensor(
                port=port, baudrate=baudrate, channel=channel,
                mapping=mapping
            )

    def connect_all(self) -> dict[str, bool]:
        """连接所有传感器，返回各端口连接结果"""
        results = {}
        for port, sensor in self.sensors.items():
            results[port] = sensor.connect()
        return results

    def disconnect_all(self):
        """断开所有传感器"""
        for sensor in self.sensors.values():
            sensor.disconnect()

    def read_all(self) -> dict[str, Optional[SensorData]]:
        """并发读取所有传感器数据"""
        results: dict[str, Optional[SensorData]] = {}
        threads = []

        def _read(port, sensor):
            results[port] = sensor.read_once()

        for port, sensor in self.sensors.items():
            if sensor.is_connected():
                t = threading.Thread(target=_read, args=(port, sensor))
                threads.append(t)
                t.start()

        for t in threads:
            t.join(timeout=1.0)

        return results

    def start_all_streaming(
        self,
        callback: Callable[[str, SensorData], None],
        interval: float = 0.05
    ):
        """启动所有传感器的流式读取

        Args:
            callback: 回调函数，参数为 (port, SensorData)
            interval: 采集间隔（秒）
        """
        for port, sensor in self.sensors.items():
            if sensor.is_connected():
                # 为每个传感器包装回调，注入 port 参数
                sensor.start_streaming(
                    lambda data, p=port: callback(p, data),
                    interval=interval
                )

    def stop_all_streaming(self):
        """停止所有传感器的流式读取"""
        for sensor in self.sensors.values():
            sensor.stop_streaming()

    def get_all_stats(self) -> dict[str, dict]:
        """获取所有传感器统计信息"""
        return {
            port: sensor.get_stats()
            for port, sensor in self.sensors.items()
        }

    def __enter__(self):
        self.connect_all()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect_all()


if __name__ == '__main__':
    import sys

    port = sys.argv[1] if len(sys.argv) > 1 else 'COM6'
    mapping_name = sys.argv[2] if len(sys.argv) > 2 else 'foot'

    with HIT_Tactile_Sensor(port, mapping=mapping_name) as sensor:
        print(f"连接到 {port}, 映射: {mapping_name}, 网格: {sensor.grid_shape}")

        # 使用 read_and_print 读取并打印
        # grid = sensor.read_and_print()
        grid = sensor.read_mapped()
        print(grid)

        if grid is not None:
            print(f"\n返回的 numpy 数组形状: {grid.shape}")
            print(f"数据类型: {grid.dtype}")
            print(f"统计: {sensor.get_stats()}")
