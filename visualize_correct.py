#!/usr/bin/env python3
"""使用正确设备ID的可视化程序"""

import time
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from matplotlib.patches import Rectangle
from HIT_Tactile_Sensor import HIT_Tactile_Sensor

# 正确的设备ID配置
PORT = '/dev/ttyUSB0'
DEVICE_ID = 0x02
CHANNEL = 0x02
COMBINED_CHANNEL = (DEVICE_ID << 4) | CHANNEL  # 0x22

class TactileVisualizer:
    def __init__(self, sensor):
        self.sensor = sensor
        self.mapping = sensor.mapping
        self.grid_rows, self.grid_cols = sensor.grid_shape
        self.active_mask = self.mapping.get_active_mask()
        self.frame_count = 0
        self.start_time = time.time()
        self._setup_figure()

    def _setup_figure(self):
        plt.rcParams['font.sans-serif'] = ['DejaVu Sans']
        self.fig, self.ax = plt.subplots(figsize=(10, 8))
        self.fig.canvas.manager.set_window_title('HIT Tactile Sensor - 请按压传感器')

        self.ax.set_xlim(-0.5, self.grid_cols - 0.5)
        self.ax.set_ylim(-0.5, self.grid_rows - 0.5)
        self.ax.set_aspect('equal')
        self.ax.invert_yaxis()

        self.ax.set_xticks(np.arange(self.grid_cols))
        self.ax.set_yticks(np.arange(self.grid_rows))
        self.ax.set_xlabel('Column', fontsize=10)
        self.ax.set_ylabel('Row', fontsize=10)

        self.cells = []
        self.texts = []

        for r in range(self.grid_rows):
            row_cells = []
            row_texts = []
            for c in range(self.grid_cols):
                is_active = self.active_mask[r, c]
                if is_active:
                    rect = Rectangle((c - 0.45, r - 0.45), 0.9, 0.9,
                                   facecolor='#1f77b4', edgecolor='white', linewidth=1.5)
                    self.ax.add_patch(rect)
                    row_cells.append(rect)
                    text = self.ax.text(c, r, '0', ha='center', va='center',
                                      fontsize=8, color='white', weight='bold')
                    row_texts.append(text)
                else:
                    rect = Rectangle((c - 0.45, r - 0.45), 0.9, 0.9,
                                   facecolor='#2C2C2C', edgecolor='#444444', linewidth=0.5)
                    self.ax.add_patch(rect)
                    row_cells.append(rect)
                    row_texts.append(None)
            self.cells.append(row_cells)
            self.texts.append(row_texts)

        self.title = self.ax.set_title(
            f'Tactile Sensor ({self.grid_rows}x{self.grid_cols}) - 设备ID: 0x{DEVICE_ID:02X}',
            fontsize=12, pad=10
        )
        self.fig.tight_layout()

    def update_frame(self, frame_num):
        grid_data = self.sensor.read_mapped(request_id=frame_num, use_lock=False)
        if grid_data is None:
            return []

        self.frame_count += 1
        artists = []

        max_value = np.max(grid_data[self.active_mask]) if np.any(self.active_mask) else 0
        vmax = max(max_value, 1.0)

        for r in range(self.grid_rows):
            for c in range(self.grid_cols):
                if not self.active_mask[r, c]:
                    continue

                value = grid_data[r, c]
                self.texts[r][c].set_text(f'{int(value)}')
                artists.append(self.texts[r][c])

                intensity = min(value / vmax, 1.0)
                color = plt.cm.Blues(0.3 + intensity * 0.7)
                self.cells[r][c].set_facecolor(color)
                artists.append(self.cells[r][c])

        if self.frame_count % 10 == 0:
            elapsed = time.time() - self.start_time
            fps = self.frame_count / elapsed if elapsed > 0 else 0
            total = grid_data.sum()
            status = "🟢 检测到压力" if total > 10 else "⚪ 无压力"
            self.title.set_text(
                f'Tactile Sensor ({self.grid_rows}x{self.grid_cols}) | '
                f'设备ID: 0x{DEVICE_ID:02X} | FPS: {fps:.1f} | 总和: {total:.1f} | {status}'
            )
            artists.append(self.title)

        return artists

    def start(self, interval=50):
        print(f"\n启动可视化...")
        print(f"  端口: {self.sensor.port}")
        print(f"  设备ID: 0x{DEVICE_ID:02X}")
        print(f"  更新间隔: {interval}ms")
        print(f"\n✨ 请用手按压传感器，观察热力图变化！")
        print("   按 Ctrl+C 或关闭窗口退出\n")

        self.ani = animation.FuncAnimation(
            self.fig, self.update_frame, interval=interval,
            blit=True, cache_frame_data=False
        )
        plt.show()

def main():
    print('='*70)
    print('HIT触觉传感器热力图可视化')
    print('='*70)
    print(f'\n连接参数:')
    print(f'  串口: {PORT}')
    print(f'  设备ID: 0x{DEVICE_ID:02X}')
    print(f'  通道: 0x{CHANNEL:02X}')
    print(f'  组合通道: 0x{COMBINED_CHANNEL:02X}')
    print()

    try:
        sensor = HIT_Tactile_Sensor(port=PORT, channel=COMBINED_CHANNEL,
                                    mapping='foot', timeout=0.01)
        if not sensor.connect():
            print('✗ 连接失败')
            return

        print('✓ 连接成功')
        visualizer = TactileVisualizer(sensor)
        visualizer.start(interval=50)
    except KeyboardInterrupt:
        print('\n用户中断')
    except Exception as e:
        print(f'\n错误: {e}')
        import traceback
        traceback.print_exc()
    finally:
        if 'sensor' in locals():
            sensor.disconnect()

if __name__ == '__main__':
    main()
