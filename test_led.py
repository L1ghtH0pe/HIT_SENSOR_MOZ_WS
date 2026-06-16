#!/usr/bin/env python3
"""桌面悬浮置顶 LED 灯 (随机渐变版, 透明背景).

特性:
   - 只显示一颗圆形 LED, 窗口背景完全透明
   - 始终置顶, 鼠标左键可拖动
   - 颜色与亮度自动随机渐变, 平滑过渡
   - 右键或 Esc 退出
"""

import colorsys
import random
import time

from PyQt5.QtCore import Qt, QTimer, QPoint
from PyQt5.QtGui import QPainter, QColor, QBrush
from PyQt5.QtWidgets import QApplication, QWidget

LED_RADIUS = 165
WIN_SIZE = LED_RADIUS * 2 + 10

FRAME_INTERVAL_MS = 33
TRANSITION_MS_RANGE = (1500, 4000)
HOLD_MS_RANGE = (200, 800)
BRIGHTNESS_RANGE = (15, 100)


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def random_vivid_rgb():
    h = random.random()
    s = random.uniform(0.7, 1.0)
    r, g, b = colorsys.hsv_to_rgb(h, s, 1.0)
    return r * 255, g * 255, b * 255


def smoothstep(t):
    t = clamp(t, 0.0, 1.0)
    return t * t * (3 - 2 * t)


def lerp(a, b, t):
    return a + (b - a) * t


class FloatingLED(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(WIN_SIZE, WIN_SIZE)

        # 初始位置: 屏幕右上角
        screen = QApplication.primaryScreen().geometry()
        self.move(screen.width() - WIN_SIZE - 40, 80)

        self._drag_origin = None

        # 渐变状态
        self._cur = self._random_target()
        self._start = self._cur
        self._target = self._random_target()
        self._t0 = time.monotonic()
        self._duration = random.uniform(*TRANSITION_MS_RANGE) / 1000.0
        self._hold_until = 0.0

        self._color = QColor(0, 0, 0)

        timer = QTimer(self)
        timer.timeout.connect(self._tick)
        timer.start(FRAME_INTERVAL_MS)

    # 拖动 --------------------------------------------------------------
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

    # 绘制 --------------------------------------------------------------
    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(QBrush(self._color))
        p.setPen(Qt.NoPen)
        cx = WIN_SIZE // 2
        cy = WIN_SIZE // 2
        p.drawEllipse(QPoint(cx, cy), LED_RADIUS, LED_RADIUS)
        p.end()

    # 渐变 --------------------------------------------------------------
    @staticmethod
    def _random_target():
        r, g, b = random_vivid_rgb()
        bri = random.uniform(*BRIGHTNESS_RANGE) / 100.0
        return (r, g, b, bri)

    def _tick(self):
        now = time.monotonic()
        if now < self._hold_until:
            r, g, b, bri = self._cur
        else:
            t = (now - self._t0) / max(0.001, self._duration)
            if t >= 1.0:
                self._cur = self._target
                self._start = self._cur
                self._target = self._random_target()
                self._duration = random.uniform(*TRANSITION_MS_RANGE) / 1000.0
                hold = random.uniform(*HOLD_MS_RANGE) / 1000.0
                self._hold_until = now + hold
                self._t0 = self._hold_until
                r, g, b, bri = self._cur
            else:
                k = smoothstep(t)
                r = lerp(self._start[0], self._target[0], k)
                g = lerp(self._start[1], self._target[1], k)
                b = lerp(self._start[2], self._target[2], k)
                bri = lerp(self._start[3], self._target[3], k)

        self._color = QColor(
            clamp(int(r * bri), 0, 255),
            clamp(int(g * bri), 0, 255),
            clamp(int(b * bri), 0, 255),
        )
        self.update()


def main():
    import sys
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(True)
    led = FloatingLED()
    led.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
