#!/usr/bin/env python3
"""触觉传感器声光反馈节点

订阅 /mx_tactile_state，根据指定传感器的压力阈值（带滞回防抖）
通过 USB CDC 向 STM32F407 下位机发送 4 字节帧 [0xA5][flag][crc_lo][crc_hi]，
驱动其 LED + 蜂鸣（flag=0 绿灯静音，flag=1 红灯+蜂鸣）。
"""

import queue
import threading
import time
from typing import Optional

import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
from mc_core_interface.msg import TactileState

import serial
import serial.tools.list_ports


# ==================== CRC-16/MCRF4XX ====================
# 与下位机 bsp/math/source/Crc.c::wCRC_Table 完全一致（位级对齐）

_CRC_TABLE = (
    0x0000, 0x1189, 0x2312, 0x329b, 0x4624, 0x57ad, 0x6536, 0x74bf,
    0x8c48, 0x9dc1, 0xaf5a, 0xbed3, 0xca6c, 0xdbe5, 0xe97e, 0xf8f7,
    0x1081, 0x0108, 0x3393, 0x221a, 0x56a5, 0x472c, 0x75b7, 0x643e,
    0x9cc9, 0x8d40, 0xbfdb, 0xae52, 0xdaed, 0xcb64, 0xf9ff, 0xe876,
    0x2102, 0x308b, 0x0210, 0x1399, 0x6726, 0x76af, 0x4434, 0x55bd,
    0xad4a, 0xbcc3, 0x8e58, 0x9fd1, 0xeb6e, 0xfae7, 0xc87c, 0xd9f5,
    0x3183, 0x200a, 0x1291, 0x0318, 0x77a7, 0x662e, 0x54b5, 0x453c,
    0xbdcb, 0xac42, 0x9ed9, 0x8f50, 0xfbef, 0xea66, 0xd8fd, 0xc974,
    0x4204, 0x538d, 0x6116, 0x709f, 0x0420, 0x15a9, 0x2732, 0x36bb,
    0xce4c, 0xdfc5, 0xed5e, 0xfcd7, 0x8868, 0x99e1, 0xab7a, 0xbaf3,
    0x5285, 0x430c, 0x7197, 0x601e, 0x14a1, 0x0528, 0x37b3, 0x263a,
    0xdecd, 0xcf44, 0xfddf, 0xec56, 0x98e9, 0x8960, 0xbbfb, 0xaa72,
    0x6306, 0x728f, 0x4014, 0x519d, 0x2522, 0x34ab, 0x0630, 0x17b9,
    0xef4e, 0xfec7, 0xcc5c, 0xddd5, 0xa96a, 0xb8e3, 0x8a78, 0x9bf1,
    0x7387, 0x620e, 0x5095, 0x411c, 0x35a3, 0x242a, 0x16b1, 0x0738,
    0xffcf, 0xee46, 0xdcdd, 0xcd54, 0xb9eb, 0xa862, 0x9af9, 0x8b70,
    0x8408, 0x9581, 0xa71a, 0xb693, 0xc22c, 0xd3a5, 0xe13e, 0xf0b7,
    0x0840, 0x19c9, 0x2b52, 0x3adb, 0x4e64, 0x5fed, 0x6d76, 0x7cff,
    0x9489, 0x8500, 0xb79b, 0xa612, 0xd2ad, 0xc324, 0xf1bf, 0xe036,
    0x18c1, 0x0948, 0x3bd3, 0x2a5a, 0x5ee5, 0x4f6c, 0x7df7, 0x6c7e,
    0xa50a, 0xb483, 0x8618, 0x9791, 0xe32e, 0xf2a7, 0xc03c, 0xd1b5,
    0x2942, 0x38cb, 0x0a50, 0x1bd9, 0x6f66, 0x7eef, 0x4c74, 0x5dfd,
    0xb58b, 0xa402, 0x9699, 0x8710, 0xf3af, 0xe226, 0xd0bd, 0xc134,
    0x39c3, 0x284a, 0x1ad1, 0x0b58, 0x7fe7, 0x6e6e, 0x5cf5, 0x4d7c,
    0xc60c, 0xd785, 0xe51e, 0xf497, 0x8028, 0x91a1, 0xa33a, 0xb2b3,
    0x4a44, 0x5bcd, 0x6956, 0x78df, 0x0c60, 0x1de9, 0x2f72, 0x3efb,
    0xd68d, 0xc704, 0xf59f, 0xe416, 0x90a9, 0x8120, 0xb3bb, 0xa232,
    0x5ac5, 0x4b4c, 0x79d7, 0x685e, 0x1ce1, 0x0d68, 0x3ff3, 0x2e7a,
    0xe70e, 0xf687, 0xc41c, 0xd595, 0xa12a, 0xb0a3, 0x8238, 0x93b1,
    0x6b46, 0x7acf, 0x4854, 0x59dd, 0x2d62, 0x3ceb, 0x0e70, 0x1ff9,
    0xf78f, 0xe606, 0xd49d, 0xc514, 0xb1ab, 0xa022, 0x92b9, 0x8330,
    0x7bc7, 0x6a4e, 0x58d5, 0x495c, 0x3de3, 0x2c6a, 0x1ef1, 0x0f78,
)
assert len(_CRC_TABLE) == 256
assert _CRC_TABLE[1] == 0x1189


def crc16_mcrf4xx(data: bytes, init: int = 0xFFFF) -> int:
    crc = init
    for b in data:
        crc = (crc >> 8) ^ _CRC_TABLE[(crc ^ b) & 0xFF]
    return crc & 0xFFFF


def build_frame(flag: int, target: int = 127, range_val: int = 20) -> bytes:
    """
    构造 6 字节下发帧：[0xA5, flag, target, range, crc_lo, crc_hi]

    Args:
        flag: 当前力度等级 (0-255)
        target: 目标值 (1-255)，下位机以此为中心计算目标区间
        range_val: 目标范围 (0-127)，目标区间为 [target-range, target+range]
    """
    target = max(1, min(255, target))  # 限制 1-255
    range_val = max(0, min(127, range_val))  # 限制 0-127
    payload = bytes((0xA5, flag & 0xFF, target & 0xFF, range_val & 0xFF))
    crc = crc16_mcrf4xx(payload)
    return payload + bytes((crc & 0xFF, (crc >> 8) & 0xFF))


def parse_stm32_frame(data: bytes) -> Optional[dict]:
    """
    解析下位机回传的 6 字节帧：[0x5A, flag, target, range, crc_lo, crc_hi]

    Returns:
        {'flag': int, 'target': int, 'range': int} 或 None（校验失败）
    """
    if len(data) != 6 or data[0] != 0x5A:
        return None
    payload = data[:4]
    crc_recv = data[4] | (data[5] << 8)
    crc_calc = crc16_mcrf4xx(payload)
    if crc_recv != crc_calc:
        return None
    return {'flag': data[1], 'target': data[2], 'range': data[3]}


# ==================== STM32 USB CDC 客户端 ====================

STM32_VID_PID = '0483:5740'
DEFAULT_PORT_FALLBACK = '/dev/ttyACM0'
RECONNECT_BACKOFF_INITIAL = 0.5
RECONNECT_BACKOFF_MAX = 5.0


def find_stm32_port() -> Optional[str]:
    for p in serial.tools.list_ports.comports():
        hwid = (p.hwid or '').upper()
        if STM32_VID_PID.upper() in hwid or 'VID:PID=0483:5740' in hwid:
            return p.device
    return None


class STM32Sender:
    """USB CDC 后台 IO：合并最新 flag 入队，断线自动重连"""

    def __init__(self, logger, port_override: str = ''):
        self.logger = logger
        self.port_override = port_override.strip()
        self._ser: Optional[serial.Serial] = None
        self._cur_port: Optional[str] = None
        self._queue: 'queue.Queue[Optional[tuple]]' = queue.Queue()  # 存储 (flag, target, range) 或 None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._io_loop,
                                        name='STM32Sender', daemon=True)

    def start(self):
        self._thread.start()

    def send_command(self, flag: int, target: int, range_val: int):
        """发送 flag + target + range 到下位机"""
        if self._stop.is_set():
            return
        # 队列存储 (flag, target, range) 三元组
        self._queue.put((int(flag) & 0xFF, int(target) & 0xFF, int(range_val) & 0xFF))

    def close(self, reset: bool = True):
        if reset:
            self._queue.put((0, 127, 20))  # 发送复位命令
        self._stop.set()
        self._queue.put(None)  # 唤醒 IO 线程
        self._thread.join(timeout=2.0)
        self._close_port()

    def _resolve_port(self) -> Optional[str]:
        if self.port_override:
            return self.port_override
        return find_stm32_port() or DEFAULT_PORT_FALLBACK

    def _open_port(self) -> bool:
        port = self._resolve_port()
        if not port:
            return False
        try:
            self._ser = serial.Serial(port, baudrate=115200, timeout=0.1,
                                      write_timeout=0.5)
            self._cur_port = port
            self.logger.info(f'STM32 connected on {port}')
            return True
        except (serial.SerialException, OSError) as e:
            self.logger.warn(f'STM32 connect failed on {port}: {e}')
            self._ser = None
            return False

    def _close_port(self):
        if self._ser is not None:
            try:
                self._ser.close()
            except Exception:
                pass
            self._ser = None
            if self._cur_port:
                self.logger.info(f'STM32 disconnected from {self._cur_port}')
                self._cur_port = None

    def _drain_latest(self, first: Optional[tuple]) -> Optional[tuple]:
        """合并队列中的最新命令（flag, target, range），返回最后一个"""
        latest = first
        try:
            while True:
                v = self._queue.get_nowait()
                if v is None:  # 关闭信号
                    return None
                latest = v
        except queue.Empty:
            pass
        return latest
        return latest

    def _io_loop(self):
        backoff = RECONNECT_BACKOFF_INITIAL
        while not self._stop.is_set():
            if self._ser is None:
                if not self._open_port():
                    self._stop.wait(backoff)
                    backoff = min(backoff * 2, RECONNECT_BACKOFF_MAX)
                    continue
                backoff = RECONNECT_BACKOFF_INITIAL

            try:
                first = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if first is None:
                continue

            cmd = self._drain_latest(first)
            if cmd is None:
                continue

            flag, target, range_val = cmd
            frame = build_frame(flag, target, range_val)
            try:
                self._ser.write(frame)
            except (serial.SerialException, OSError) as e:
                self.logger.warn(f'STM32 write failed: {e}, will reconnect')
                self._close_port()
                # 把这个命令重新放回，重连后立即同步
                try:
                    self._queue.put_nowait(cmd)
                except queue.Full:
                    pass


# ==================== ROS2 节点 ====================

DEFAULT_SENSOR_ID = 'hit_foot_left_2'
DEFAULT_PRESS_ON = 300.0
DEFAULT_PRESS_OFF = 30.0
DEFAULT_RESYNC_INTERVAL = 2.0
DEFAULT_METRIC = 'sum'
DEFAULT_HAND = 'left'  # 'left' / 'right' / 'both'
DEFAULT_TARGET = 127   # 下位机目标值，范围 1-255
DEFAULT_RANGE = 20     # 下位机目标范围，范围 0-127

# hand 参数对应的 actuator 名称
HAND_TO_ACTUATOR = {
    'left':  ['left_end'],
    'right': ['right_end'],
    'both':  ['left_end', 'right_end'],
}


class TactileFeedbackNode(Node):
    def __init__(self):
        super().__init__('tactile_feedback')

        self.declare_parameter('sensor_id', DEFAULT_SENSOR_ID)
        self.declare_parameter('metric', DEFAULT_METRIC)
        self.declare_parameter('press_on', DEFAULT_PRESS_ON)
        self.declare_parameter('press_off', DEFAULT_PRESS_OFF)
        self.declare_parameter('port_override', '')
        self.declare_parameter('resync_interval', DEFAULT_RESYNC_INTERVAL)
        self.declare_parameter('hand', DEFAULT_HAND)
        self.declare_parameter('target', DEFAULT_TARGET)
        self.declare_parameter('range', DEFAULT_RANGE)

        self.sensor_id = self.get_parameter('sensor_id').value
        self.metric = self.get_parameter('metric').value
        self.press_on = float(self.get_parameter('press_on').value)
        self.press_off = float(self.get_parameter('press_off').value)
        self.resync_interval = float(self.get_parameter('resync_interval').value)
        port_override = self.get_parameter('port_override').value

        # 读取下位机参数：target 和 range
        self.stm32_target = int(self.get_parameter('target').value)
        self.stm32_range = int(self.get_parameter('range').value)
        # 限制范围
        self.stm32_target = max(1, min(255, self.stm32_target))
        self.stm32_range = max(0, min(127, self.stm32_range))

        # 解析 hand 参数，得到要监听的 actuator 名称白名单
        hand = str(self.get_parameter('hand').value).lower().strip()
        if hand not in HAND_TO_ACTUATOR:
            self.get_logger().warn(
                f"未知的 hand 参数 '{hand}'，回退到 '{DEFAULT_HAND}'。"
                f"支持的值：{list(HAND_TO_ACTUATOR.keys())}")
            hand = DEFAULT_HAND
        self.hand = hand
        self.allowed_actuators = set(HAND_TO_ACTUATOR[hand])

        if self.press_off >= self.press_on:
            self.get_logger().warn(
                f'press_off ({self.press_off}) >= press_on ({self.press_on})，'
                f'滞回失效，建议 press_off < press_on')

        self.state_alarm = False
        self.last_send_time = 0.0
        self.last_log_time = 0.0
        self.frame_count = 0
        self._last_force = 0

        qos = QoSProfile(
            reliability=ReliabilityPolicy.RELIABLE,
            history=HistoryPolicy.KEEP_LAST,
            depth=1,
        )
        self.subscription = self.create_subscription(
            TactileState, '/mx_tactile_state', self.callback, qos
        )

        self.sender = STM32Sender(self.get_logger(), port_override=port_override)
        self.sender.start()

        # 计算目标区间（便于日志显示）
        target_low = max(0, self.stm32_target - self.stm32_range)
        target_high = min(255, self.stm32_target + self.stm32_range)

        self.get_logger().info(
            f'tactile_feedback started: hand={self.hand} '
            f'(actuators={sorted(self.allowed_actuators)}) '
            f'metric={self.metric} thresholds={self.press_off}/{self.press_on} '
            f'STM32_target={self.stm32_target}±{self.stm32_range} ({target_low}-{target_high})'
        )

    def _extract_grid(self, msg: TactileState) -> Optional[np.ndarray]:
        """提取所选手（hand 参数指定）的传感器数据，融合后返回最大值网格"""
        all_grids = []
        for actuator in msg.actuators:
            # 只处理白名单内的 actuator（左手/右手/全部）
            if actuator.name not in self.allowed_actuators:
                continue
            for sensor in actuator.sensors:
                expected = sensor.rows * sensor.cols * max(sensor.channels, 1)
                if len(sensor.data) != expected or expected == 0:
                    continue
                grid = np.array(sensor.data, dtype=np.float32).reshape(
                    sensor.rows, sensor.cols
                )
                all_grids.append(grid)

        if not all_grids:
            return None

        # 单个传感器直接返回；多个传感器逐元素取最大值
        if len(all_grids) == 1:
            return all_grids[0]
        else:
            return np.maximum.reduce(all_grids)

    def callback(self, msg: TactileState):
        grid = self._extract_grid(msg)
        if grid is None:
            return

        v = float(grid.sum()) if self.metric == 'sum' else float(grid.max())
        now = time.time()

        # 三阶段力度引导映射
        # 目标：sum=100±20 (80-120)
        # 编码：0-84(太弱) | 85-170(目标) | 171-255(太强)
        TARGET_CENTER = 150.0
        TARGET_RANGE = 20.0
        TARGET_LOW = TARGET_CENTER - TARGET_RANGE   # 80
        TARGET_HIGH = TARGET_CENTER + TARGET_RANGE  # 120

        STAGE_WEAK_MAX = 84
        STAGE_TARGET_MIN = 85
        STAGE_TARGET_MAX = 170
        STAGE_STRONG_MIN = 171

        if v < TARGET_LOW:
            # 阶段1：太弱 (sum < 80)
            # 映射到 0-84，越接近目标值越大
            ratio = v / TARGET_LOW if TARGET_LOW > 0 else 0
            force = int(ratio * STAGE_WEAK_MAX)
        elif v <= TARGET_HIGH:
            # 阶段2：目标区间 (80 <= sum <= 120)
            # 映射到 85-170，中心点127
            ratio = (v - TARGET_LOW) / (TARGET_HIGH - TARGET_LOW)
            force = int(STAGE_TARGET_MIN + ratio * (STAGE_TARGET_MAX - STAGE_TARGET_MIN))
        else:
            # 阶段3：太强 (sum > 120)
            # 映射到 171-255，超出越多值越大
            # 设定一个合理的上限，比如 sum=300 对应 force=255
            max_over = 180.0  # sum超出120后再+180达到满量程
            over = min(v - TARGET_HIGH, max_over)
            ratio = over / max_over
            force = int(STAGE_STRONG_MIN + ratio * (255 - STAGE_STRONG_MIN))

        force = max(0, min(255, force))

        # 状态判定和阶段识别
        prev_alarm = self.state_alarm
        self.state_alarm = (force > 0)

        # 判断当前阶段（用于日志）
        if force <= STAGE_WEAK_MAX:
            stage = "WEAK"
        elif force <= STAGE_TARGET_MAX:
            stage = "TARGET"
        else:
            stage = "STRONG"

        edge = self.state_alarm != prev_alarm
        heartbeat = (now - self.last_send_time) >= self.resync_interval
        force_changed = abs(force - self._last_force) > 10  # 力度变化超过 10

        # 发送条件：状态翻转 or 心跳 or 力度显著变化
        if edge or heartbeat or (self.state_alarm and force_changed):
            self.sender.send_command(force, self.stm32_target, self.stm32_range)
            self._last_force = force
            self.last_send_time = now
            if edge:
                self.get_logger().info(
                    f'state -> {"ALARM" if self.state_alarm else "IDLE"} '
                    f'(force={force} v={v:.1f} stage={stage})'
                )
            elif force_changed:
                self.get_logger().info(f'force updated: {force} (v={v:.1f} stage={stage})')

        self.frame_count += 1
        if now - self.last_log_time >= 5.0:
            self.get_logger().info(
                f'frames={self.frame_count} v={v:.1f} force={force} stage={stage} '
                f'state={"ALARM" if self.state_alarm else "IDLE"}'
            )
            self.last_log_time = now

    def destroy_node(self):
        try:
            self.sender.close(reset=True)
        except Exception as e:
            self.get_logger().warn(f'sender close error: {e}')
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = TactileFeedbackNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
