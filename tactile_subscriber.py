#!/usr/bin/env python3
"""
途见触觉传感器 ROS2 订阅节点
订阅 /mx_tactile_state，实时显示左右手各 2 个传感器的力分布热力图
"""

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.cm as cm
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
from mc_core_interface.msg import TactileState


class TactileSubscriber(Node):
    def __init__(self):
        super().__init__('tactile_subscriber')

        qos = QoSProfile(
            reliability=ReliabilityPolicy.RELIABLE,
            history=HistoryPolicy.KEEP_LAST,
            depth=1,
        )

        self.subscription = self.create_subscription(
            TactileState, '/mx_tactile_state', self.callback, qos
        )

        # 初始化 matplotlib - 2x2 布局显示 4 个传感器
        plt.ion()
        self.fig, self.axes = plt.subplots(2, 2, figsize=(12, 10))
        self.fig.suptitle('Tactile State - 4 Sensors', fontsize=14)

        # 传感器位置映射
        self.images = {}
        self.sensor_positions = {
            'tujian_23x29_left_1': (0, 0),
            'tujian_23x29_left_2': (0, 1),
            'tujian_23x29_right_1': (1, 0),
            'tujian_23x29_right_2': (1, 1),
        }

        # 初始化空白图表
        for sensor_id, (row, col) in self.sensor_positions.items():
            ax = self.axes[row, col]
            ax.set_title(sensor_id)
            ax.set_xlabel('Column')
            ax.set_ylabel('Row')
            self.images[sensor_id] = None  # 延迟初始化，等待实际数据

        self.fig.tight_layout()
        plt.show(block=False)
        plt.pause(0.01)

        self.get_logger().info('Tactile subscriber started, waiting for data...')

    def callback(self, msg: TactileState):
        for actuator in msg.actuators:
            for sensor in actuator.sensors:
                sensor_id = sensor.sensor_id

                if sensor_id not in self.sensor_positions:
                    continue

                if len(sensor.data) != sensor.rows * sensor.cols * sensor.channels:
                    self.get_logger().warn(
                        f'{sensor_id}: data size mismatch '
                        f'(expected {sensor.rows * sensor.cols * sensor.channels}, got {len(sensor.data)})'
                    )
                    continue

                matrix = np.array(sensor.data).reshape(sensor.rows, sensor.cols)
                row, col = self.sensor_positions[sensor_id]
                ax = self.axes[row, col]

                # 应用双阈值：小于阈值的值mask掉，显示为灰色背景
                threshold = 0.01
                masked_matrix = np.ma.masked_where(matrix < threshold, matrix)

                # 计算非零区域的百分位数作为vmax，避免极值影响显示
                nonzero_values = matrix[matrix >= threshold]
                if len(nonzero_values) > 0:
                    vmax = np.percentile(nonzero_values, 95)
                    vmax = max(vmax, 0.05)  # 确保至少有一个合理的范围
                else:
                    vmax = 0.1

                # 首次收到数据时初始化热力图
                if self.images[sensor_id] is None:
                    # 创建colormap并设置masked区域的颜色
                    cmap = cm.get_cmap('plasma').copy()
                    cmap.set_bad(color='#2a2a2a')  # 设置mask区域（无接触）为深灰色

                    im = ax.imshow(masked_matrix, cmap=cmap, vmin=threshold, vmax=vmax,
                                   interpolation='nearest', origin='upper')
                    ax.set_xlabel(f'Column (0-{sensor.cols - 1})')
                    ax.set_ylabel(f'Row (0-{sensor.rows - 1})')
                    self.fig.colorbar(im, ax=ax, fraction=0.046)
                    self.images[sensor_id] = im
                    self.fig.tight_layout()
                else:
                    im = self.images[sensor_id]
                    im.set_data(masked_matrix)
                    im.set_clim(vmin=threshold, vmax=vmax)

                ax.set_title(
                    f'{sensor_id} ({sensor.rows}×{sensor.cols})\n'
                    f'sum={matrix.sum():.2f}  max={matrix.max():.3f}  mean={matrix.mean():.4f}  '
                    f'p95={vmax:.3f}  thr={threshold:.3f}'
                )

        self.fig.canvas.draw_idle()
        self.fig.canvas.flush_events()


def main(args=None):
    rclpy.init(args=args)
    node = TactileSubscriber()

    try:
        while rclpy.ok():
            rclpy.spin_once(node, timeout_sec=0.01)
            plt.pause(0.01)
    except KeyboardInterrupt:
        pass
    finally:
        plt.close('all')
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()