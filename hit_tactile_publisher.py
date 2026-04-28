#!/usr/bin/env python3
"""
HIT触觉传感器 ROS2 发布节点
使用 HIT_Tactile_Sensor 读取数据，发布到 /mx_tactile_state
支持 --fake 模式生成假数据用于调试
"""

import math
import time
import threading
from typing import Optional

import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
from mc_core_interface.msg import TactileState, TactileActuator, TactileSensor


# ==================== 配置 ====================

SENSOR_PORT = '/dev/ttyUSB0'
SENSOR_BAUDRATE = 921600
SENSOR_CHANNEL = 0x12
SENSOR_MAPPING = 'foot'

ACTUATOR_NAME = 'left_end'
ACTUATOR_TYPE = '2f_v1'
SENSOR_ID = 'hit_foot_left_1'

PUBLISH_RATE = 100.0  # Hz
READ_INTERVAL = 0.005  # 5ms 读取间隔
LOG_INTERVAL = 1.0


# ==================== 数据读取器 ====================

class HITDataReader:
    """独立线程持续读取 HIT 触觉传感器数据，启动时自动去底噪"""

    def __init__(self, logger, port: str = SENSOR_PORT,
                 baudrate: int = SENSOR_BAUDRATE,
                 channel: int = SENSOR_CHANNEL,
                 mapping: str = SENSOR_MAPPING):
        from HIT_Tactile_Sensor import HIT_Tactile_Sensor

        self.logger = logger
        self.sensor = HIT_Tactile_Sensor(
            port=port, baudrate=baudrate,
            channel=channel, mapping=mapping
        )
        self.grid_shape = self.sensor.grid_shape

        self.data_cache: Optional[np.ndarray] = None
        self.base_offset: Optional[np.ndarray] = None
        self.cache_lock = threading.Lock()
        self.running = False
        self.read_thread: Optional[threading.Thread] = None

    def connect(self) -> bool:
        ok = self.sensor.connect()
        if ok:
            self.logger.info(f"HIT sensor connected on {self.sensor.port}")
        else:
            self.logger.error(f"HIT sensor connection failed on {self.sensor.port}")
        return ok

    def _auto_calibrate(self, wait_time: float = 2.0, samples: int = 50):
        self.logger.info(f"等待传感器数据稳定 ({wait_time}s)，请勿触摸传感器...")
        time.sleep(wait_time)

        self.logger.info(f"正在自动采集初始底噪 (采样数: {samples})...")
        collected = []
        for _ in range(samples):
            grid = self.sensor.read_mapped(use_lock=True)
            if grid is not None:
                collected.append(grid)
            time.sleep(0.1)

        if collected:
            self.base_offset = np.mean(collected, axis=0).astype(np.float32)
            self.logger.info("校准完成，已保存初始底噪。")
        else:
            self.base_offset = np.zeros(self.grid_shape, dtype=np.float32)
            self.logger.error("未采集到有效数据，校准失败！使用零偏移。")

    def start(self):
        if not self.connect():
            raise RuntimeError("无法连接传感器")
        self._auto_calibrate()
        self.running = True
        self.read_thread = threading.Thread(target=self._read_loop, daemon=True)
        self.read_thread.start()
        self.logger.info("Data reader thread started")

    def stop(self):
        self.running = False
        if self.read_thread:
            self.read_thread.join(timeout=1.0)
        self.sensor.disconnect()
        self.logger.info("Sensor disconnected")

    def _read_loop(self):
        while self.running:
            start_time = time.time()
            try:
                grid = self.sensor.read_mapped(use_lock=True)
                if grid is not None:
                    processed = grid - self.base_offset
                    processed = np.maximum(processed, 0)
                    with self.cache_lock:
                        self.data_cache = processed.astype(np.float32)
            except Exception as e:
                if self.running:
                    self.logger.warn(f"读取失败: {e}")

            elapsed = time.time() - start_time
            sleep_time = READ_INTERVAL - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

    def get_cached_data(self) -> Optional[np.ndarray]:
        with self.cache_lock:
            return self.data_cache


# ==================== 假数据发布节点 ====================

class FakeHITPublisher(Node):
    def __init__(self):
        super().__init__('fake_hit_tactile_publisher')
        from sensor_mapping import SensorMapping
        self.mapping = SensorMapping(SENSOR_MAPPING)

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
        rows, cols = self.mapping.grid_shape
        sensor_count = self.mapping.get_sensor_count()

        cx = sensor_count / 2 + (sensor_count / 4) * math.sin(self.frame * 0.05)
        fake_flat = np.array([
            math.exp(-((i - cx) ** 2) / 32.0) for i in range(sensor_count)
        ], dtype=np.float32)
        grid = self.mapping.map_data_to_grid(fake_flat)

        sensor_msg = TactileSensor()
        sensor_msg.sensor_id = SENSOR_ID
        sensor_msg.rows = grid.shape[0]
        sensor_msg.cols = grid.shape[1]
        sensor_msg.channels = 1
        sensor_msg.data = grid.flatten().tolist()

        actuator = TactileActuator()
        actuator.name = ACTUATOR_NAME
        actuator.actuator_type = ACTUATOR_TYPE
        actuator.sensors = [sensor_msg]

        msg = TactileState()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = ''
        msg.actuators = [actuator]

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
        grid = self.data_reader.get_cached_data()
        if grid is None:
            return

        sensor_msg = TactileSensor()
        sensor_msg.sensor_id = SENSOR_ID
        sensor_msg.rows = grid.shape[0]
        sensor_msg.cols = grid.shape[1]
        sensor_msg.channels = 1
        sensor_msg.data = grid.flatten().tolist()

        actuator = TactileActuator()
        actuator.name = ACTUATOR_NAME
        actuator.actuator_type = ACTUATOR_TYPE
        actuator.sensors = [sensor_msg]

        msg = TactileState()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = ''
        msg.actuators = [actuator]

        self.publisher.publish(msg)
        self.frame += 1

        now = time.time()
        if now - self.last_log_time >= LOG_INTERVAL:
            self.get_logger().info(
                f'{SENSOR_ID}: sum={grid.sum():.3f} max={grid.max():.3f} '
                f'frame={self.frame}'
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
