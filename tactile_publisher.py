#!/usr/bin/env python3
"""
途见触觉传感器 ROS2 发布节点
支持假数据模式（FakeTactilePublisher）和真实数据模式（TactilePublisher）
使用 mc_core_interface 编译后的消息类型发布到 /mx_tactile_state
"""

import math
import time
import threading
from typing import Optional, Dict

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
            {'port': 0, 'sensor_id': 'tujian_23x29_left_1'},
            {'port': 2, 'sensor_id': 'tujian_23x29_left_2'},
        ]
    },
    {
        'name': 'right_end',
        'actuator_type': '2f_v1',
        'sensors': [
            {'port': 1, 'sensor_id': 'tujian_23x29_right_1'},
            {'port': 3, 'sensor_id': 'tujian_23x29_right_2'},
        ]
    },
]

SENSOR_CONFIG = {
    'sensor_class': 'Usb32',
    'sensor_shape': [32, 32],
    'splitted_file_path': 'config_mapping_plane.json',
    'calibrate_file_path': 'calibration_example_p2p.json',
    'timeout': 0.03,
    'y_lim': [0, 0.5],
}

# 可用区域裁剪配置（从32x32中提取有效区域）
ROI_CONFIG = {
    'row_start': 0,
    'row_end': 23,    # 不包含此索引
    'col_start': 0,
    'col_end': 29,    # 不包含此索引
}

PUBLISH_RATE = 100.0  # Hz
READ_INTERVAL = 0.002  # 2ms 读取间隔
LOG_INTERVAL = 1.0   # 日志打印间隔（秒）


# ==================== 假数据发布节点 ====================

def crop_to_roi(data: np.ndarray) -> np.ndarray:
    """
    从32x32数据中裁剪出可用区域
    """
    return data[
        ROI_CONFIG['row_start']:ROI_CONFIG['row_end'],
        ROI_CONFIG['col_start']:ROI_CONFIG['col_end']
    ]

def generate_fake_force(rows: int, cols: int, frame: int) -> tuple:
    """
    生成一帧假的法向力数据 (channels=1)
    模拟一个高斯压力点在传感器上缓慢移动
    返回裁剪后的数据和对应的行列数
    """
    cx = cols / 2 + (cols / 4) * math.sin(frame * 0.05)
    cy = rows / 2 + (rows / 4) * math.cos(frame * 0.07)

    y, x = np.mgrid[0:rows, 0:cols]
    dist = (x - cx) ** 2 + (y - cy) ** 2
    sigma = 4.0
    force = np.exp(-dist / (2 * sigma ** 2)).astype(np.float32)

    # 裁剪到可用区域
    force_cropped = crop_to_roi(force)

    return force_cropped.flatten().tolist(), force_cropped.shape[0], force_cropped.shape[1]


class FakeTactilePublisher(Node):
    def __init__(self):
        super().__init__('fake_tactile_publisher')

        qos = QoSProfile(
            reliability=ReliabilityPolicy.RELIABLE,
            history=HistoryPolicy.KEEP_LAST,
            depth=1,
        )

        self.publisher = self.create_publisher(
            TactileState, '/mx_tactile_state', qos
        )

        self.timer = self.create_timer(1.0 / PUBLISH_RATE, self.publish_callback)
        self.frame = 0

        self.get_logger().info(
            f'Fake tactile publisher started at {PUBLISH_RATE}Hz'
        )

    def publish_callback(self):
        # 左执行器 - 两个传感器
        left_sensor_1 = TactileSensor()
        left_sensor_1.sensor_id = 'tujian_23x29_left_1'
        data_1, rows_1, cols_1 = generate_fake_force(32, 32, self.frame)
        left_sensor_1.rows = rows_1
        left_sensor_1.cols = cols_1
        left_sensor_1.channels = 1
        left_sensor_1.data = data_1

        left_sensor_2 = TactileSensor()
        left_sensor_2.sensor_id = 'tujian_23x29_left_2'
        data_2, rows_2, cols_2 = generate_fake_force(32, 32, self.frame + 25)
        left_sensor_2.rows = rows_2
        left_sensor_2.cols = cols_2
        left_sensor_2.channels = 1
        left_sensor_2.data = data_2

        left_actuator = TactileActuator()
        left_actuator.name = 'left_end'
        left_actuator.actuator_type = '2f_v1'
        left_actuator.sensors = [left_sensor_1, left_sensor_2]

        # 右执行器 - 两个传感器
        right_sensor_1 = TactileSensor()
        right_sensor_1.sensor_id = 'tujian_23x29_right_1'
        data_3, rows_3, cols_3 = generate_fake_force(32, 32, self.frame + 50)
        right_sensor_1.rows = rows_3
        right_sensor_1.cols = cols_3
        right_sensor_1.channels = 1
        right_sensor_1.data = data_3

        right_sensor_2 = TactileSensor()
        right_sensor_2.sensor_id = 'tujian_23x29_right_2'
        data_4, rows_4, cols_4 = generate_fake_force(32, 32, self.frame + 75)
        right_sensor_2.rows = rows_4
        right_sensor_2.cols = cols_4
        right_sensor_2.channels = 1
        right_sensor_2.data = data_4

        right_actuator = TactileActuator()
        right_actuator.name = 'right_end'
        right_actuator.actuator_type = '2f_v1'
        right_actuator.sensors = [right_sensor_1, right_sensor_2]

        msg = TactileState()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = ''
        msg.actuators = [left_actuator, right_actuator]

        self.publisher.publish(msg)

        self.frame += 1
        if self.frame % 100 == 0:
            self.get_logger().info(f'Published frame {self.frame}')


# ==================== 真实数据发布节点 ====================

class TactileDataReader:
    """独立线程持续读取触觉传感器数据并缓存，启动时自动去底噪"""

    def __init__(self, logger):
        from Usb_API_stable_Tujian.TactileDataProvider import TactileDataProvider

        self.logger = logger
        self.providers: Dict[int, any] = {}
        self.data_cache: Dict[int, Optional[np.ndarray]] = {}
        self.base_offsets: Dict[int, np.ndarray] = {}
        self.cache_lock = threading.Lock()
        self.running = False
        self.read_thread = None

        rows, cols = SENSOR_CONFIG['sensor_shape']
        all_ports = [s['port'] for act in ACTUATORS for s in act['sensors']]

        for port in all_ports:
            try:
                provider = TactileDataProvider(
                    port=port,
                    sensor_class=SENSOR_CONFIG['sensor_class'],
                    sensor_shape=SENSOR_CONFIG['sensor_shape'],
                    splitted_file_path=SENSOR_CONFIG['splitted_file_path'],
                    calibrate_file_path=SENSOR_CONFIG['calibrate_file_path'],
                    filtering_coloring=False,
                    tfd=False,
                    y_lim=SENSOR_CONFIG['y_lim'],
                    timeout=SENSOR_CONFIG['timeout'],
                )
                provider.start()
                self.providers[port] = provider
                self.data_cache[port] = np.zeros((rows, cols), dtype=np.float32)
                self.base_offsets[port] = np.zeros((rows, cols), dtype=np.float32)
                self.logger.info(f"Started provider for port {port}")
            except Exception as e:
                self.logger.error(f"Failed to start provider for port {port}: {e}")

    def _auto_calibrate(self, wait_time=2.0, samples=50):
        """
        🟢 自动触发逻辑：先等待数据稳定，再读取若干帧取平均值作为初始底噪
        """
        self.logger.info(f">>> 等待传感器数据稳定 ({wait_time}秒)，请勿触摸传感器...")
        time.sleep(wait_time)

        self.logger.info(f">>> 正在自动采集初始底噪，请勿触摸传感器 (采样数: {samples})...")
        temp_data = {port: [] for port in self.providers.keys()}
        count = 0
        while count < samples:
            for port, provider in self.providers.items():
                data = provider.get_latest_data()
                if data is not None and data[0] is not None:
                    force_dict = data[0]
                    key = list(force_dict.keys())[0]
                    temp_data[port].append(force_dict[key])
            count += 1
            time.sleep(0.1) # 100ms 采样间隔
        for port in self.providers.keys():
            if temp_data[port]:
                self.base_offsets[port] = np.mean(temp_data[port], axis=0)
                self.logger.info(f"端口 {port} 校准完成，已保存初始默认值。")
            else:
                self.logger.error(f"端口 {port} 未采集到有效数据，校准失败！")
    def start(self):
        """启动读取线程"""
        self._auto_calibrate()
        self.running = True
        self.read_thread = threading.Thread(target=self._read_loop, daemon=True)
        self.read_thread.start()
        self.logger.info("Data reader thread started")

    def stop(self):
        """停止读取线程"""
        self.running = False
        if self.read_thread:
            self.read_thread.join(timeout=1.0)

        for port, provider in self.providers.items():
            try:
                provider.stop()
                self.logger.info(f"Stopped provider for port {port}")
            except Exception as e:
                self.logger.warn(f"Error stopping provider for port {port}: {e}")

    def _read_loop(self):
        """持续读取数据的循环"""
        while self.running:
            start_time = time.time()

            for port, provider in self.providers.items():
                try:
                    data = provider.get_latest_data()
                    if data is not None and data[0] is not None:
                        force_dict = data[0]
                        key = list(force_dict.keys())[0]
                        raw_matrix = force_dict[key]
                        processed_matrix = raw_matrix - self.base_offsets[port]
                        processed_matrix = np.maximum(processed_matrix, 0)

                        with self.cache_lock:
                            self.data_cache[port] = processed_matrix.astype(np.float32)
                except Exception as e:
                    if self.running:  # 只在运行时打印错误
                        self.logger.warn(f"Failed to read from port {port}: {e}")

            # 保持 2ms 读取间隔
            elapsed = time.time() - start_time
            sleep_time = READ_INTERVAL - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

    def get_cached_data(self, port: int) -> Optional[np.ndarray]:
        """获取缓存的数据"""
        with self.cache_lock:
            return self.data_cache.get(port)


class TactilePublisher(Node):
    def __init__(self):
        super().__init__('tactile_publisher')

        qos = QoSProfile(
            reliability=ReliabilityPolicy.RELIABLE,
            history=HistoryPolicy.KEEP_LAST,
            depth=1,
        )

        self.publisher = self.create_publisher(
            TactileState, '/mx_tactile_state', qos
        )

        # 启动数据读取器
        self.data_reader = TactileDataReader(self.get_logger())
        self.data_reader.start()

        self.timer = self.create_timer(1.0 / PUBLISH_RATE, self.publish_callback)
        self.last_log_time = time.time()
        self.frame = 0

        self.get_logger().info(
            f'Tactile publisher started at {PUBLISH_RATE}Hz'
        )

    def publish_callback(self):
        actuators = []
        log_parts = []

        for act in ACTUATORS:
            sensors = []

            for sensor_cfg in act['sensors']:
                port = sensor_cfg['port']
                force_matrix = self.data_reader.get_cached_data(port)

                if force_matrix is None:
                    self.get_logger().warn(f"No data for port {port}, skipping")
                    continue

                # 裁剪到可用区域
                force_matrix = crop_to_roi(force_matrix)

                # 构造 TactileSensor
                sensor = TactileSensor()
                sensor.sensor_id = sensor_cfg['sensor_id']
                sensor.rows = force_matrix.shape[0]
                sensor.cols = force_matrix.shape[1]
                sensor.channels = 1
                sensor.data = force_matrix.flatten().tolist()

                sensors.append(sensor)

                log_parts.append(
                    f"{sensor_cfg['sensor_id']}: sum={force_matrix.sum():.3f} "
                    f"max={force_matrix.max():.3f}"
                )

            # 构造 TactileActuator
            actuator = TactileActuator()
            actuator.name = act['name']
            actuator.actuator_type = act['actuator_type']
            actuator.sensors = sensors

            actuators.append(actuator)

        msg = TactileState()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = ''
        msg.actuators = actuators
        self.publisher.publish(msg)
        self.frame += 1

        # 每秒打印一次统计日志
        now = time.time()
        if log_parts and now - self.last_log_time >= LOG_INTERVAL:
            self.get_logger().info(' | '.join(log_parts))
            self.last_log_time = now

    def destroy_node(self):
        self.data_reader.stop()
        super().destroy_node()


# ==================== 入口 ====================

def main(args=None):
    import sys
    use_fake = '--fake' in sys.argv

    rclpy.init(args=args)
    node = FakeTactilePublisher() if use_fake else TactilePublisher()

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
