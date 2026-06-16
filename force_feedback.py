#!/usr/bin/env python3
"""触觉传感器合力反馈节点 - LED 颜色 + 声音强度可视化.

订阅 /mx_tactile_state, 将面阵数值累加得到合力 (g -> N),
通过 LED 颜色 (绿->黄->红) 和蜂鸣音频率/音量反映力的大小.

用法:
   python3 force_feedback.py                  # LED + 声音同时启用
   python3 force_feedback.py --led-only       # 仅 LED
   python3 force_feedback.py --audio-only     # 仅声音
   python3 force_feedback.py --max-force 20   # 设置量程为 20N
"""

import argparse
import colorsys
import math
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
import wave
from pathlib import Path

import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
from mc_core_interface.msg import TactileState

from PyQt5.QtCore import Qt, QTimer, QPoint, pyqtSignal
from PyQt5.QtGui import QPainter, QColor, QBrush, QFont
from PyQt5.QtWidgets import QApplication, QWidget

# ==================== 配置 ====================

G_TO_NEWTON = 0.00981         # 1g (gram-force) = 0.00981 N
DEFAULT_MAX_FORCE_N = 10.0    # 量程上限 (N), 对应红色
DEFAULT_MIN_FORCE_N = 0.0     # 量程下限 (N), 对应绿色

SENSOR_IDS = ['hit_foot_left_1', 'hit_foot_left_2']

LED_RADIUS = 360
WIN_SIZE = LED_RADIUS * 2 + 60

# 声音参数
BEEP_FREQ_MIN = 300           # 力最小时蜂鸣频率 Hz
BEEP_FREQ_MAX = 1200          # 力最大时蜂鸣频率 Hz
BEEP_DURATION = 0.08          # 单次蜂鸣时长 s
BEEP_INTERVAL_MIN = 0.08      # 力最大时蜂鸣间隔 s
BEEP_INTERVAL_MAX = 1.0       # 力最小时蜂鸣间隔 s
BEEP_THRESHOLD = 0.05         # 低于此比例不发声 (避免静止时噪声)

# ==================== 工具函数 ====================

PLACEHOLDER_CONTINUE = None


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def force_to_ratio(force_n, min_n, max_n):
    """将力值映射到 0~1 比例."""
    if max_n <= min_n:
        return 0.0
    return clamp((force_n - min_n) / (max_n - min_n), 0.0, 1.0)


def ratio_to_color(ratio):
    """0=绿色, 0.5=黄色, 1.0=红色 (HSV 色相 120->60->0)."""
    hue = (1.0 - ratio) * 120.0 / 360.0  # 0.333 -> 0
    r, g, b = colorsys.hsv_to_rgb(hue, 1.0, 1.0)
    return int(r * 255), int(g * 255), int(b * 255)


# ==================== 声音模块 ====================

class AudioFeedback:
    """通过系统音频播放蜂鸣音反馈力大小."""

    def __init__(self):
        self._player = shutil.which("paplay") or shutil.which("aplay")
        self._running = False
        self._ratio = 0.0
        self._lock = threading.Lock()
        self._thread = None

    def start(self):
        if not self._player:
            print("[AudioFeedback] 未找到 paplay/aplay, 声音反馈不可用", file=sys.stderr)
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=1.0)

    def set_ratio(self, ratio):
        with self._lock:
            self._ratio = clamp(ratio, 0.0, 1.0)

    def _loop(self):
        while self._running:
            with self._lock:
                ratio = self._ratio

            if ratio < BEEP_THRESHOLD:
                time.sleep(0.1)
                continue

            freq = BEEP_FREQ_MIN + (BEEP_FREQ_MAX - BEEP_FREQ_MIN) * ratio
            interval = BEEP_INTERVAL_MAX - (BEEP_INTERVAL_MAX - BEEP_INTERVAL_MIN) * ratio

            self._play_beep(freq, BEEP_DURATION, amplitude=0.3 + 0.7 * ratio)
            time.sleep(interval)

    def _play_beep(self, freq, duration, amplitude=0.5, sample_rate=22050):
        n_frames = int(duration * sample_rate)
        amp = amplitude * 32767
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp_path = Path(tmp.name)
        tmp.close()
        try:
            with wave.open(str(tmp_path), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(sample_rate)
                for i in range(n_frames):
                    env = min(1.0, i / 200, (n_frames - i) / 200)
                    sample = int(amp * env * math.sin(2 * math.pi * freq * i / sample_rate))
                    w.writeframesraw(struct.pack("<h", sample))
            subprocess.run([self._player, str(tmp_path)],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        finally:
            tmp_path.unlink(missing_ok=True)


# ==================== LED 窗口 ====================

class ForceLED(QWidget):
    force_updated = pyqtSignal(float, float)  # (force_n, ratio)

    def __init__(self, max_force_n=DEFAULT_MAX_FORCE_N):
        super().__init__()
        self._max_force = max_force_n
        self._force_n = 0.0
        self._ratio = 0.0
        self._color = QColor(0, 255, 0)

        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(WIN_SIZE, WIN_SIZE)

        screen = QApplication.primaryScreen().geometry()
        self.move(screen.width() - WIN_SIZE - 40, 80)

        self._drag_origin = None
        self.force_updated.connect(self._on_force_updated)

    def set_force(self, force_n, ratio):
        self.force_updated.emit(force_n, ratio)

    def _on_force_updated(self, force_n, ratio):
        self._force_n = force_n
        self._ratio = ratio
        r, g, b = ratio_to_color(ratio)
        brightness = 0.3 + 0.7 * ratio
        self._color = QColor(
            clamp(int(r * brightness), 0, 255),
            clamp(int(g * brightness), 0, 255),
            clamp(int(b * brightness), 0, 255),
        )
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(QBrush(self._color))
        p.setPen(Qt.NoPen)
        cx = cy = WIN_SIZE // 2
        p.drawEllipse(QPoint(cx, cy), LED_RADIUS, LED_RADIUS)

        p.setPen(QColor(255, 255, 255, 200))
        p.setFont(QFont("Mono", 14, QFont.Bold))
        text = f"{self._force_n:.2f} N"
        p.drawText(self.rect(), Qt.AlignCenter, text)
        p.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_origin = event.globalPos() - self.frameGeometry().topLeft()
        elif event.button() == Qt.RightButton:
            QApplication.quit()

    def mouseMoveEvent(self, event):
        if self._drag_origin and event.buttons() & Qt.LeftButton:
            self.move(event.globalPos() - self._drag_origin)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            QApplication.quit()

    def closeEvent(self, event):
        QApplication.quit()
        event.accept()


# ==================== ROS2 订阅节点 ====================

class ForceFeedbackNode(Node):
    def __init__(self, sensor_ids, max_force_n):
        super().__init__('force_feedback_node')
        self.sensor_ids = sensor_ids
        self.max_force_n = max_force_n
        self.current_force_n = 0.0
        self.current_ratio = 0.0
        self._lock = threading.Lock()

        qos = QoSProfile(
            reliability=ReliabilityPolicy.RELIABLE,
            history=HistoryPolicy.KEEP_LAST,
            depth=1,
        )
        self.subscription = self.create_subscription(
            TactileState, '/mx_tactile_state', self.callback, qos
        )
        self.get_logger().info(
            f'Force feedback node started, sensors={sensor_ids}, max={max_force_n}N'
        )

    def callback(self, msg: TactileState):
        forces = []
        for actuator in msg.actuators:
            for sensor in actuator.sensors:
                if sensor.sensor_id not in self.sensor_ids:
                    continue
                data = np.array(sensor.data, dtype=np.float32)
                force_g = float(data.sum())
                force_n = force_g * G_TO_NEWTON
                forces.append(force_n)

        if not forces:
            return

        # 多传感器取最大值
        total_force_n = max(forces)
        ratio = force_to_ratio(total_force_n, DEFAULT_MIN_FORCE_N, self.max_force_n)

        with self._lock:
            self.current_force_n = total_force_n
            self.current_ratio = ratio

    def get_force(self):
        with self._lock:
            return self.current_force_n, self.current_ratio


# ==================== 主程序 ====================

def parse_args():
    p = argparse.ArgumentParser(description="触觉传感器合力反馈 (LED + 声音)")
    p.add_argument("--led-only", action="store_true", help="仅启用 LED 反馈")
    p.add_argument("--audio-only", action="store_true", help="仅启用声音反馈")
    p.add_argument("--max-force", type=float, default=DEFAULT_MAX_FORCE_N,
                   help=f"量程上限 N (默认 {DEFAULT_MAX_FORCE_N})")
    p.add_argument("--sensors", nargs="+", default=None,
                   help=f"传感器 ID 列表 (默认 {SENSOR_IDS})")
    return p.parse_args()


def main():
    args = parse_args()
    sensor_ids = args.sensors if args.sensors else SENSOR_IDS
    use_led = not args.audio_only
    use_audio = not args.led_only

    rclpy.init()
    node = ForceFeedbackNode(sensor_ids, args.max_force)

    # ROS2 spin 在后台线程
    ros_thread = threading.Thread(target=rclpy.spin, args=(node,), daemon=True)
    ros_thread.start()

    # 声音反馈
    audio = None
    if use_audio:
        audio = AudioFeedback()
        audio.start()

    # LED 反馈 (需要 Qt 事件循环在主线程)
    if use_led:
        app = QApplication(sys.argv)
        app.setQuitOnLastWindowClosed(True)
        led = ForceLED(max_force_n=args.max_force)
        led.show()

        # 定时从 ROS 节点拉取力值更新 LED 和声音
        def poll_force():
            force_n, ratio = node.get_force()
            led.set_force(force_n, ratio)
            if audio:
                audio.set_ratio(ratio)

        poll_timer = QTimer()
        poll_timer.timeout.connect(poll_force)
        poll_timer.start(30)  # ~33 Hz

        try:
            sys.exit(app.exec_())
        finally:
            if audio:
                audio.stop()
            node.destroy_node()
            rclpy.shutdown()
    else:
        # 无 LED 模式: 纯终端 + 声音
        print(f"[force_feedback] 仅声音模式, 量程 0~{args.max_force}N, Ctrl+C 退出")
        try:
            while rclpy.ok():
                force_n, ratio = node.get_force()
                if audio:
                    audio.set_ratio(ratio)
                bar_len = int(ratio * 30)
                bar = "█" * bar_len + "░" * (30 - bar_len)
                print(f"\r  {force_n:6.2f} N [{bar}] {ratio*100:5.1f}%", end="", flush=True)
                time.sleep(0.05)
        except KeyboardInterrupt:
            print()
        finally:
            if audio:
                audio.stop()
            node.destroy_node()
            rclpy.shutdown()


if __name__ == "__main__":
    main()
