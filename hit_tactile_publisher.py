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
                'port': '/dev/ttyUSB1',
                'channel': 0x12,
                'sensor_id': 'hit_foot_left_1',
                'mapping': 'foot',
            },
            {
                'port': '/dev/ttyUSB0',
                'channel': 0x22,
                'sensor_id': 'hit_foot_left_2',
                'mapping': 'foot',
            },
        ]
    },
    # {
    #     'name': 'right_end',
    #     'actuator_type': '2f_v1',
    #     'sensors': [
    #         {
    #             'port': '/dev/ttyUSB2',
    #             'channel': 0x32,
    #             'sensor_id': 'hit_foot_right_1',
    #             'mapping': 'foot',
    #         },
    #         {
    #             'port': '/dev/ttyUSB3',
    #             'channel': 0x42,
    #             'sensor_id': 'hit_foot_right_2',
    #             'mapping': 'foot',
    #         },
    #     ]
    # },
]

SENSOR_BAUDRATE = 921600

PUBLISH_RATE = 100.0  # Hz
READ_INTERVAL = 0.005  # 5ms 读取间隔 (200Hz)
LOG_INTERVAL = 10.0
DATA_FRESHNESS_THRESHOLD = 0.015  # 15ms，超过此时间不发布数据


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
        self.sensors = {}
        self.grid_shapes = {}
        self.data_cache = {}
        self.data_timestamps = {}
        self.base_offsets = {}
        self.cache_lock = threading.Lock()
        self.running = False
        self.read_threads: List[threading.Thread] = []

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
        all_ok = True
        for sid, sensor in self.sensors.items():
            ok = sensor.connect()
            if ok:
                self.logger.info(f"[{sid}] connected on {sensor.port}")
            else:
                self.logger.error(f"[{sid}] connection failed on {sensor.port}")
                all_ok = False
        return all_ok

    def start(self):
        if not self.connect():
            raise RuntimeError("无法连接所有传感器")
        self.running = True

        # 为每个传感器启动独立读取线程
        for sid, sensor in self.sensors.items():
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
        for sid, sensor in self.sensors.items():
            sensor.disconnect()
            self.logger.info(f"[{sid}] disconnected")

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
