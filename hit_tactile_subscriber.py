#!/usr/bin/env python3
"""
HIT触觉传感器 ROS2 订阅节点
订阅 /mx_tactile_state，实时显示 HIT 传感器的力分布热力图
"""

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.cm as cm
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
from mc_core_interface.msg import TactileState


SENSOR_ID = 'hit_foot_left_1'


class HITTactileSubscriber(Node):
    def __init__(self):
        super().__init__('hit_tactile_subscriber')

        qos = QoSProfile(
            reliability=ReliabilityPolicy.RELIABLE,
            history=HistoryPolicy.KEEP_LAST,
            depth=1,
        )

        self.subscription = self.create_subscription(
            TactileState, '/mx_tactile_state', self.callback, qos
        )

        plt.ion()
        self.fig, self.ax = plt.subplots(1, 1, figsize=(8, 10))
        self.fig.suptitle('HIT Tactile Sensor', fontsize=14)
        self.ax.set_title(SENSOR_ID)
        self.ax.set_xlabel('Column')
        self.ax.set_ylabel('Row')
        self.image = None

        self.fig.tight_layout()
        plt.show(block=False)
        plt.pause(0.01)

        self.get_logger().info('HIT tactile subscriber started, waiting for data...')

    def callback(self, msg: TactileState):
        for actuator in msg.actuators:
            for sensor in actuator.sensors:
                if sensor.sensor_id != SENSOR_ID:
                    continue

                expected = sensor.rows * sensor.cols * sensor.channels
                if len(sensor.data) != expected:
                    self.get_logger().warn(
                        f'{sensor.sensor_id}: data size mismatch '
                        f'(expected {expected}, got {len(sensor.data)})'
                    )
                    continue

                matrix = np.array(sensor.data).reshape(sensor.rows, sensor.cols)

                threshold = 0.01
                masked_matrix = np.ma.masked_where(matrix < threshold, matrix)

                nonzero_values = matrix[matrix >= threshold]
                if len(nonzero_values) > 0:
                    vmax = np.percentile(nonzero_values, 95)
                    vmax = max(vmax, 0.05)
                else:
                    vmax = 0.1

                if self.image is None:
                    cmap = cm.get_cmap('plasma')
                    cmap.set_bad(color='#2a2a2a')

                    self.image = self.ax.imshow(
                        masked_matrix, cmap=cmap,
                        vmin=threshold, vmax=vmax,
                        interpolation='nearest', origin='upper'
                    )
                    self.ax.set_xlabel(f'Column (0-{sensor.cols - 1})')
                    self.ax.set_ylabel(f'Row (0-{sensor.rows - 1})')
                    self.fig.colorbar(self.image, ax=self.ax, fraction=0.046)
                    self.fig.tight_layout()
                else:
                    self.image.set_data(masked_matrix)
                    self.image.set_clim(vmin=threshold, vmax=vmax)

                self.ax.set_title(
                    f'{sensor.sensor_id} ({sensor.rows}x{sensor.cols})\n'
                    f'sum={matrix.sum():.2f}  max={matrix.max():.3f}  '
                    f'mean={matrix.mean():.4f}  p95={vmax:.3f}'
                )

        self.fig.canvas.draw_idle()
        self.fig.canvas.flush_events()


def main(args=None):
    rclpy.init(args=args)
    node = HITTactileSubscriber()

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
