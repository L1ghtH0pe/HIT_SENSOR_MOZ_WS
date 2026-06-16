#!/usr/bin/env python3
"""实时监控传感器数据 - 终端版本"""

import time
from HIT_Tactile_Sensor import HIT_Tactile_Sensor

def main():
    port = '/dev/ttyUSB0'
    sensor = HIT_Tactile_Sensor(port=port, channel=0x22, mapping='foot')

    if not sensor.connect():
        print("连接失败！")
        return

    print("="*70)
    print("实时监控传感器数据 - 请按压传感器")
    print("="*70)
    print("按 Ctrl+C 停止")
    print()

    try:
        frame_count = 0
        while True:
            grid = sensor.read_mapped(request_id=frame_count % 256)

            if grid is not None:
                total = grid.sum()
                max_val = grid.max()

                # 找到最大值的位置
                max_pos = None
                if max_val > 0:
                    import numpy as np
                    max_idx = np.unravel_index(grid.argmax(), grid.shape)
                    max_pos = max_idx

                # 显示进度条
                bar_len = int(min(total / 100, 50))
                bar = "█" * bar_len + "░" * (50 - bar_len)

                status = "🟢 有压力" if total > 10 else "⚪ 无压力"

                print(f"\r帧{frame_count:5d} | 总和:{total:7.1f} | 最大:{max_val:5.1f} | {status} | [{bar}]", end="", flush=True)

                if max_pos:
                    print(f" @ ({max_pos[0]},{max_pos[1]})", end="", flush=True)

                frame_count += 1

            time.sleep(0.05)  # 20Hz

    except KeyboardInterrupt:
        print("\n\n停止监控")
    finally:
        sensor.disconnect()

if __name__ == '__main__':
    main()
