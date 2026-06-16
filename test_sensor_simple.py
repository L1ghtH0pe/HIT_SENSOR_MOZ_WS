#!/usr/bin/env python3
"""简单的传感器测试脚本 - 诊断通信问题"""

import sys
from HIT_Tactile_Sensor import HIT_Tactile_Sensor

def main():
    port = '/dev/ttyUSB0'

    print("="*70)
    print("HIT触觉传感器诊断测试")
    print("="*70)
    print(f"\n串口: {port}")
    print(f"波特率: 921600")
    print(f"通道: 0x22 (device_id=0x02, channel=0x02)")
    print()

    # 尝试连接传感器
    print("正在连接传感器...")
    sensor = HIT_Tactile_Sensor(port=port, channel=0x22, mapping='foot')

    if not sensor.connect():
        print("✗ 连接失败！")
        print("\n可能的原因：")
        print("  1. 串口被其他程序占用")
        print("  2. 传感器未上电")
        print("  3. USB线未连接")
        return 1

    print("✓ 连接成功！")
    print()

    # 尝试读取5次数据
    print("正在读取数据（共5次）...")
    print("-"*70)

    success_count = 0
    for i in range(5):
        grid = sensor.read_mapped(request_id=i)

        if grid is not None:
            success_count += 1
            total = grid.sum()
            max_val = grid.max()
            print(f"第{i+1}次: ✓ 成功  总和={total:.1f}  最大值={max_val:.1f}")

            # 显示数据的简单可视化
            if max_val > 10:  # 如果有明显的压力
                print(f"       检测到压力！位置：", end="")
                rows, cols = grid.shape
                for r in range(rows):
                    for c in range(cols):
                        if grid[r, c] > 10:
                            print(f"({r},{c})={grid[r,c]:.0f} ", end="")
                print()
        else:
            print(f"第{i+1}次: ✗ 读取失败")

    print("-"*70)
    print(f"\n成功率: {success_count}/5")

    # 显示统计信息
    stats = sensor.get_stats()
    print(f"\n传感器统计:")
    print(f"  总帧数: {stats['frame_count']}")
    print(f"  错误数: {stats['error_count']}")
    print(f"  错误率: {stats['error_rate']*100:.1f}%")

    sensor.disconnect()
    print("\n✓ 测试完成")

    if success_count == 0:
        print("\n⚠️  警告：所有读取都失败了！")
        print("\n可能的原因：")
        print("  1. 通道号不对（当前是0x22，尝试扫描设备ID）")
        print("  2. 传感器未正确初始化")
        print("  3. 波特率不匹配")
        print("\n建议：运行 python3 scan_hit_tactile_id.py 扫描设备")
        return 1
    elif success_count < 5:
        print("\n⚠️  警告：部分读取失败，通信不稳定")
        return 1
    else:
        print("\n✓ 传感器工作正常！")
        print("\n现在可以运行可视化程序：")
        print("  python3 update_visual_tactile.py /dev/ttyUSB0 foot 50")
        return 0

if __name__ == '__main__':
    sys.exit(main())
