"""HIT触觉传感器实时可视化 - 基于 HIT_Tactile_Sensor 类"""

import time
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from matplotlib.patches import Rectangle
from HIT_Tactile_Sensor import HIT_Tactile_Sensor


class TactileVisualizer:
    """触觉传感器热力图可视化"""

    def __init__(self, sensor: HIT_Tactile_Sensor):
        self.sensor = sensor
        self.mapping = sensor.mapping
        self.grid_rows, self.grid_cols = sensor.grid_shape
        self.active_mask = self.mapping.get_active_mask()

        self.frame_count = 0
        self.start_time = time.time()

        self._setup_figure()

    def _setup_figure(self):
        plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'Arial']
        plt.rcParams['axes.unicode_minus'] = False

        self.fig, self.ax = plt.subplots(
            figsize=(self.grid_cols * 0.8 + 2, self.grid_rows * 0.8 + 2)
        )
        self.fig.canvas.manager.set_window_title('HIT触觉传感器热力图')

        self.ax.set_xlim(-0.5, self.grid_cols - 0.5)
        self.ax.set_ylim(-0.5, self.grid_rows - 0.5)
        self.ax.set_aspect('equal')
        self.ax.invert_yaxis()

        self.ax.set_xticks(np.arange(self.grid_cols))
        self.ax.set_yticks(np.arange(self.grid_rows))
        self.ax.set_xticklabels(np.arange(1, self.grid_cols + 1))
        self.ax.set_yticklabels(np.arange(1, self.grid_rows + 1))
        self.ax.set_xlabel('列', fontsize=10)
        self.ax.set_ylabel('行', fontsize=10)

        for spine in self.ax.spines.values():
            spine.set_visible(False)

        self.cells = []
        self.texts = []

        for r in range(self.grid_rows):
            row_cells = []
            row_texts = []
            for c in range(self.grid_cols):
                is_active = self.active_mask[r, c]

                if is_active:
                    rect = Rectangle(
                        (c - 0.45, r - 0.45), 0.9, 0.9,
                        facecolor='#1f77b4',
                        edgecolor='white',
                        linewidth=1.5
                    )
                    self.ax.add_patch(rect)
                    row_cells.append(rect)

                    text = self.ax.text(
                        c, r, '0',
                        ha='center', va='center',
                        fontsize=8, color='white',
                        weight='bold'
                    )
                    row_texts.append(text)
                else:
                    rect = Rectangle(
                        (c - 0.45, r - 0.45), 0.9, 0.9,
                        facecolor='#2C2C2C',
                        edgecolor='#444444',
                        linewidth=0.5
                    )
                    self.ax.add_patch(rect)
                    row_cells.append(rect)
                    row_texts.append(None)

            self.cells.append(row_cells)
            self.texts.append(row_texts)

        self.title = self.ax.set_title(
            f'触觉传感器阵列 ({self.grid_rows}x{self.grid_cols}, '
            f'{self.mapping.get_sensor_count()}个传感器)',
            fontsize=12, pad=10
        )
        self.fig.tight_layout()

    def update_frame(self, frame_num):
        grid_data = self.sensor.read_mapped(use_lock=False)
        if grid_data is None:
            return []

        self.frame_count += 1

        artists = []
        max_value = np.max(grid_data[self.active_mask])
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
            self.title.set_text(
                f'触觉传感器阵列 ({self.grid_rows}x{self.grid_cols}) | '
                f'端口: {self.sensor.port} | FPS: {fps:.1f} | 最大值: {int(max_value)}'
            )
            artists.append(self.title)

        return artists

    def start(self, interval: int = 50):
        print(f"\n启动可视化...")
        print(f"  端口: {self.sensor.port}")
        print(f"  更新间隔: {interval}ms")
        print(f"  目标帧率: {1000/interval:.1f} FPS")
        print("\n按 Ctrl+C 或关闭窗口退出\n")

        self.ani = animation.FuncAnimation(
            self.fig,
            self.update_frame,
            interval=interval,
            blit=True,
            cache_frame_data=False
        )
        plt.show()


def main():
    import sys

    port = sys.argv[1] if len(sys.argv) > 1 else '/dev/ttyUSB0'
    mapping = sys.argv[2] if len(sys.argv) > 2 else 'foot'
    interval = int(sys.argv[3]) if len(sys.argv) > 3 else 50

    print('='*70)
    print('HIT触觉传感器热力图可视化')
    print('='*70)
    print(f'\n连接参数:')
    print(f'  串口: {port}')
    print(f'  波特率: 921600')
    print(f'  映射配置: {mapping}')
    print()

    try:
        with HIT_Tactile_Sensor(port, mapping=mapping, timeout=0.01) as sensor:
            print('✓ 连接成功')
            visualizer = TactileVisualizer(sensor)
            visualizer.start(interval=interval)
    except KeyboardInterrupt:
        print('\n用户中断')
    except Exception as e:
        print(f'\n错误: {e}')
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    main()
