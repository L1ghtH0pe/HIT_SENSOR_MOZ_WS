#!/usr/bin/env python3
"""
HIT触觉传感器 ROS2 发布节点
使用 HIT_Tactile_Sensor 读取数据，发布到 /mx_tactile_state
支持 --fake 模式生成假数据用于调试
"""

import math
import time
import threading
from typing import Optional, Tuple, List

import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
from mc_core_interface.msg import TactileState, TactileActuator, TactileSensor


# ==================== 配置 ====================

ACTUATORS = [
    {
        'name': 'left_end',
        'actuator_type': '2f_v1',
        'sensors': [
            {
                # udev 固定符号链接 -> 物理USB口绑定，不受ttyUSB编号变化影响
                'port': '/dev/hit_tactile_left_1',
                'channel': 0x12,  # device_id=0x01
                'sensor_id': 'hit_foot_left_1',
                'mapping': 'foot',
            },
            {
                'port': '/dev/hit_tactile_left_2',
                'channel': 0x22,  # device_id=0x02
                'sensor_id': 'hit_foot_left_2',
                'mapping': 'foot',
            },
        ]
    },
    {
        'name': 'right_end',
        'actuator_type': '2f_v1',
        'sensors': [
            {
                'port': '/dev/hit_tactile_right_1',
                'channel': 0x32,  # device_id=0x03
                'sensor_id': 'hit_foot_right_1',
                'mapping': 'foot',
            },
            {
                'port': '/dev/hit_tactile_right_2',
                'channel': 0x42,  # device_id=0x04
                'sensor_id': 'hit_foot_right_2',
                'mapping': 'foot',
            },
        ]
    },
]

SENSOR_BAUDRATE = 921600

PUBLISH_RATE = 100.0  # Hz
READ_INTERVAL = 0.005  # 5ms 读取间隔 (200Hz)
LOG_INTERVAL = 10.0
DATA_FRESHNESS_THRESHOLD = 0.015  # 15ms，超过此时间不发布数据


# ==================== 端口自动检测 ====================
# ttyUSB 编号由 USB 枚举顺序决定，重新插拔/重启后可能对调。
# 这里在启动时扫描每个端口的 device_id，按 device_id 自动匹配端口，
# 不再依赖写死的 port，避免连错传感器。

import struct
import glob
import os
import serial as _serial


def _scan_crc16(data: bytes) -> int:
    crc = 0x0000
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if (crc & 0x0001) else (crc >> 1)
    return crc & 0xFFFF


def _build_probe_frame(device_id: int, channel: int = 0x02) -> bytes:
    id_chan = ((device_id & 0x0F) << 4) | (channel & 0x0F)
    payload = b'\x01'
    length = struct.pack('<H', len(payload))
    checksum = struct.pack('<H', _scan_crc16(payload))
    return b'\x3C\x3C' + bytes([id_chan, 0x01]) + length + payload + checksum + b'\x3E\x3E'


def _has_valid_response(data: bytes) -> bool:
    i = 0
    while i < len(data) - 9:
        if data[i:i+2] != b'\x3C\x3C':
            i += 1
            continue
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
        if recv_crc == _scan_crc16(recv_payload):
            return True
        i += 1
    return False


def detect_device_id(port: str, baudrate: int = SENSOR_BAUDRATE,
                     id_range=range(1, 8)) -> Optional[int]:
    """探测指定串口上的设备 ID，返回第一个响应的 ID，无响应返回 None"""
    try:
        ser = _serial.Serial(port, baudrate, timeout=0.1)
    except Exception:
        return None
    try:
        time.sleep(0.05)
        for dev_id in id_range:
            try:
                ser.reset_input_buffer()
                ser.write(_build_probe_frame(dev_id))
                time.sleep(0.02)
                resp = ser.read(4096)
                if resp and _has_valid_response(resp):
                    return dev_id
            except Exception:
                pass
    finally:
        ser.close()
    return None


def resolve_ports(actuator_configs, logger=None) -> None:
    """校验每个传感器配置的端口，并按 device_id 做一致性检查。

    本项目使用 udev 固定符号链接（/dev/hit_tactile_*），符号链接由物理USB口
    绑定，编号不会变化。这里只探测配置里实际用到的端口（符号链接），
    不再扫描全部 /dev/ttyUSB*，从而避开 RM500Q(5G模块) 等无关串口设备。

    - 若端口能探测到 device_id 且与配置的 channel 匹配 -> 正常
    - 若探测到的 device_id 与配置不符 -> 仅警告（可能是符号链接绑错口）
    - 若端口不存在/无响应 -> 仅警告，保留配置（交给后续 connect 处理）
    """
    for act in actuator_configs:
        for cfg in act['sensors']:
            port = cfg['port']
            want_id = (cfg['channel'] >> 4) & 0x0F

            if not os.path.exists(port):
                if logger:
                    logger.warn(
                        f"[{cfg['sensor_id']}] 端口 {port} 不存在，"
                        f"请检查 udev 符号链接或设备连接")
                continue

            got_id = detect_device_id(port)
            if got_id is None:
                if logger:
                    logger.warn(
                        f"[{cfg['sensor_id']}] {port} 无响应（device_id 期望0x{want_id:02X}）")
            elif got_id != want_id:
                if logger:
                    logger.warn(
                        f"[{cfg['sensor_id']}] {port} 实际 device_id=0x{got_id:02X}，"
                        f"但配置期望 0x{want_id:02X}（符号链接可能绑错物理口）")
            else:
                if logger:
                    logger.info(
                        f"[{cfg['sensor_id']}] {port} -> device_id=0x{got_id:02X} ✓")


# ==================== 数据读取器 ====================

class HITDataReader:
    """独立线程持续读取多个 HIT 触觉传感器数据，启动时自动去底噪

    优化特性：
    - 每个传感器独立线程并发读取，避免延迟累积
    - 数据带时间戳，确保发布的是最新数据
    - 自动调整读取频率以匹配发布频率
    """

    def __init__(self, logger, actuator_configs=ACTUATORS,
                 baudrate: int = SENSOR_BAUDRATE):
        from HIT_Tactile_Sensor import HIT_Tactile_Sensor

        self.logger = logger

        # 启动时按 device_id 自动匹配端口，避免 ttyUSB 编号变化导致连错
        resolve_ports(actuator_configs, logger)

        self.sensors = {}
        self.grid_shapes = {}
        self.data_cache = {}
        self.data_timestamps = {}
        self.base_offsets = {}
        self.cache_lock = threading.Lock()
        self.running = False
        self.read_threads: List[threading.Thread] = []
        self.connected_sids: List[str] = []

        # 性能统计
        self.read_counts = {}
        self.error_counts = {}
        for act in actuator_configs:
            for cfg in act['sensors']:
                sid = cfg['sensor_id']
                self.read_counts[sid] = 0
                self.error_counts[sid] = 0

        for act in actuator_configs:
            for cfg in act['sensors']:
                sid = cfg['sensor_id']
                sensor = HIT_Tactile_Sensor(
                    port=cfg['port'], baudrate=baudrate,
                    channel=cfg['channel'], mapping=cfg['mapping']
                )
                self.sensors[sid] = sensor
                self.grid_shapes[sid] = sensor.grid_shape
                self.data_cache[sid] = None
                self.data_timestamps[sid] = 0.0
                self.base_offsets[sid] = np.zeros(sensor.grid_shape, dtype=np.float32)

    def connect(self) -> bool:
        """连接所有传感器，记录成功连上的。返回是否至少有一个连上。"""
        self.connected_sids = []
        for sid, sensor in self.sensors.items():
            try:
                ok = sensor.connect()
            except Exception as e:
                ok = False
                self.logger.error(f"[{sid}] connect 异常: {e}")
            if ok:
                self.logger.info(f"[{sid}] connected on {sensor.port}")
                self.connected_sids.append(sid)
            else:
                self.logger.error(f"[{sid}] connection failed on {sensor.port}")
        total = len(self.sensors)
        n = len(self.connected_sids)
        if n == total:
            self.logger.info(f"全部 {total} 个传感器连接成功")
        elif n > 0:
            self.logger.warn(
                f"部分连接：{n}/{total} 个传感器在线 "
                f"({', '.join(self.connected_sids)})，其余跳过")
        return n > 0

    def start(self):
        if not self.connect():
            raise RuntimeError("没有任何传感器连接成功，请检查设备连接和权限")
        self.running = True

        # 只为成功连上的传感器启动读取线程
        for sid in self.connected_sids:
            sensor = self.sensors[sid]
            thread = threading.Thread(
                target=self._read_loop_single,
                args=(sid, sensor),
                daemon=True,
                name=f"Reader-{sid}"
            )
            self.read_threads.append(thread)
            thread.start()

        self.logger.info(f"Started {len(self.read_threads)} data reader threads")

    def stop(self):
        self.running = False
        for thread in self.read_threads:
            thread.join(timeout=1.0)
        # 只断开成功连上的传感器
        for sid in getattr(self, 'connected_sids', list(self.sensors.keys())):
            try:
                self.sensors[sid].disconnect()
                self.logger.info(f"[{sid}] disconnected")
            except Exception:
                pass

    def _read_loop_single(self, sensor_id: str, sensor):
        """单个传感器的独立读取循环"""
        consecutive_errors = 0
        max_consecutive_errors = 10
        request_id = 0

        while self.running:
            start_time = time.time()
            try:
                grid = sensor.read_mapped(request_id=request_id, use_lock=True)
                if grid is not None:
                    processed = grid - self.base_offsets[sensor_id]
                    processed = np.maximum(processed, 0)

                    with self.cache_lock:
                        self.data_cache[sensor_id] = processed.astype(np.float32)
                        self.data_timestamps[sensor_id] = time.time()
                        self.read_counts[sensor_id] += 1

                    consecutive_errors = 0
                    request_id = (request_id + 1) % 256
                else:
                    consecutive_errors += 1
                    with self.cache_lock:
                        self.error_counts[sensor_id] += 1

            except Exception as e:
                consecutive_errors += 1
                with self.cache_lock:
                    self.error_counts[sensor_id] += 1
                if self.running and consecutive_errors <= 3:
                    self.logger.warn(f"[{sensor_id}] 读取失败: {e}")

            # 如果连续失败太多次，降低读取频率避免资源浪费
            if consecutive_errors >= max_consecutive_errors:
                self.logger.error(f"[{sensor_id}] 连续失败{consecutive_errors}次，降低读取频率")
                time.sleep(1.0)
                consecutive_errors = 0
                continue

            elapsed = time.time() - start_time
            sleep_time = READ_INTERVAL - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

    def get_cached_data(self, sensor_id: str) -> Optional[np.ndarray]:
        """获取缓存的传感器数据"""
        with self.cache_lock:
            return self.data_cache.get(sensor_id)

    def get_cached_data_with_timestamp(self, sensor_id: str) -> Tuple[Optional[np.ndarray], float]:
        """获取缓存的传感器数据及其时间戳"""
        with self.cache_lock:
            data = self.data_cache.get(sensor_id)
            timestamp = self.data_timestamps.get(sensor_id, 0.0)
            return data, timestamp


# ==================== 假数据发布节点 ====================

class FakeHITPublisher(Node):
    def __init__(self):
        super().__init__('fake_hit_tactile_publisher')
        from sensor_mapping import SensorMapping
        self.mappings = {
            cfg['sensor_id']: SensorMapping(cfg['mapping'])
            for act in ACTUATORS for cfg in act['sensors']
        }

        qos = QoSProfile(
            reliability=ReliabilityPolicy.RELIABLE,
            history=HistoryPolicy.KEEP_LAST,
            depth=1,
        )
        self.publisher = self.create_publisher(TactileState, '/mx_tactile_state', qos)
        self.timer = self.create_timer(1.0 / PUBLISH_RATE, self.publish_callback)
        self.frame = 0
        self.get_logger().info(f'Fake HIT tactile publisher started at {PUBLISH_RATE}Hz')

    def publish_callback(self):
        actuators = []
        sensor_index = 0

        for act_cfg in ACTUATORS:
            sensors = []
            for cfg in act_cfg['sensors']:
                mapping = self.mappings[cfg['sensor_id']]
                sensor_count = mapping.get_sensor_count()
                cx = sensor_count / 2 + (sensor_count / 4) * math.sin((self.frame + sensor_index * 25) * 0.05)
                fake_flat = np.array([
                    math.exp(-((i - cx) ** 2) / 32.0) for i in range(sensor_count)
                ], dtype=np.float32)
                grid = mapping.map_data_to_grid(fake_flat)

                sensor_msg = TactileSensor()
                sensor_msg.sensor_id = cfg['sensor_id']
                sensor_msg.rows = grid.shape[0]
                sensor_msg.cols = grid.shape[1]
                sensor_msg.channels = 1
                sensor_msg.data = grid.flatten().tolist()
                sensors.append(sensor_msg)
                sensor_index += 1

            actuator = TactileActuator()
            actuator.name = act_cfg['name']
            actuator.actuator_type = act_cfg['actuator_type']
            actuator.sensors = sensors
            actuators.append(actuator)

        msg = TactileState()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = ''
        msg.actuators = actuators

        self.publisher.publish(msg)
        self.frame += 1
        if self.frame % 100 == 0:
            self.get_logger().info(f'Published frame {self.frame}')


# ==================== 真实数据发布节点 ====================

class HITTactilePublisher(Node):
    def __init__(self):
        super().__init__('hit_tactile_publisher')

        qos = QoSProfile(
            reliability=ReliabilityPolicy.RELIABLE,
            history=HistoryPolicy.KEEP_LAST,
            depth=1,
        )
        self.publisher = self.create_publisher(TactileState, '/mx_tactile_state', qos)

        self.data_reader = HITDataReader(self.get_logger())
        self.data_reader.start()

        self.timer = self.create_timer(1.0 / PUBLISH_RATE, self.publish_callback)
        self.last_log_time = time.time()
        self.frame = 0
        self.get_logger().info(f'HIT tactile publisher started at {PUBLISH_RATE}Hz')

    def publish_callback(self):
        actuators = []
        log_parts = []
        now = time.time()
        stale_data_count = 0
        fresh_data_count = 0

        for act_cfg in ACTUATORS:
            sensors = []

            for cfg in act_cfg['sensors']:
                grid, timestamp = self.data_reader.get_cached_data_with_timestamp(cfg['sensor_id'])
                if grid is None:
                    continue

                # 严格检查数据新鲜度
                data_age = now - timestamp
                if data_age > DATA_FRESHNESS_THRESHOLD:
                    stale_data_count += 1
                    if self.frame % 100 == 0:  # 每100帧警告一次
                        self.get_logger().warn(
                            f"[{cfg['sensor_id']}] 数据过时 {data_age*1000:.1f}ms，跳过发布"
                        )
                    continue  # 跳过过时数据，不发布

                fresh_data_count += 1
                sensor_msg = TactileSensor()
                sensor_msg.sensor_id = cfg['sensor_id']
                sensor_msg.rows = grid.shape[0]
                sensor_msg.cols = grid.shape[1]
                sensor_msg.channels = 1
                sensor_msg.data = grid.flatten().tolist()
                sensors.append(sensor_msg)

                log_parts.append(
                    f"{cfg['sensor_id']}: sum={grid.sum():.1f} max={grid.max():.1f} age={data_age*1000:.1f}ms"
                )

            actuator = TactileActuator()
            actuator.name = act_cfg['name']
            actuator.actuator_type = act_cfg['actuator_type']
            actuator.sensors = sensors
            actuators.append(actuator)

        # 只有当有新鲜数据时才发布
        if not any(a.sensors for a in actuators):
            if self.frame % 100 == 0:
                self.get_logger().warn(f"无新鲜数据可发布 (过时: {stale_data_count})")
            return

        msg = TactileState()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = ''
        msg.actuators = actuators

        self.publisher.publish(msg)
        self.frame += 1

        # 定期输出性能统计
        if log_parts and now - self.last_log_time >= LOG_INTERVAL:
            stats_parts = []
            for sid in self.data_reader.read_counts.keys():
                read_cnt = self.data_reader.read_counts[sid]
                err_cnt = self.data_reader.error_counts[sid]
                success_rate = (read_cnt - err_cnt) / read_cnt * 100 if read_cnt > 0 else 0
                stats_parts.append(f"{sid}: {success_rate:.1f}%")

            self.get_logger().info(
                ' | '.join(log_parts) + f' | frame={self.frame} | ' +
                '成功率: ' + ', '.join(stats_parts)
            )
            self.last_log_time = now

    def destroy_node(self):
        self.data_reader.stop()
        super().destroy_node()


# ==================== 入口 ====================

def main(args=None):
    import sys
    use_fake = '--fake' in sys.argv

    rclpy.init(args=args)
    node = FakeHITPublisher() if use_fake else HITTactilePublisher()

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
