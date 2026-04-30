#!/usr/bin/env python3
"""
HIT触觉传感器 ROS2 订阅节点
订阅 /mx_tactile_state，实时显示两路 HIT 传感器的力分布热力图
"""

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.cm as cm
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
from mc_core_interface.msg import TactileState


SENSOR_IDS = ['hit_foot_left_1','hit_foot_left_2']
# SENSOR_IDS = ['hit_foot_left_1', 'hit_foot_right_1', 'hit_foot_left_2', 'hit_foot_right_2']


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
        self.fig, self.axes = plt.subplots(2, 2, figsize=(14, 12))
        self.fig.suptitle('HIT Tactile Sensors', fontsize=14)

        self.images = {}
        for idx, sid in enumerate(SENSOR_IDS):
            row, col = divmod(idx, 2)
            ax = self.axes[row, col]
            ax.set_title(sid)
            ax.set_xlabel('Column')
            ax.set_ylabel('Row')
            self.images[sid] = None

        self.fig.tight_layout()
        plt.show(block=False)
        plt.pause(0.01)

        self.get_logger().info('HIT tactile subscriber started, waiting for data...')

    def callback(self, msg: TactileState):
        for actuator in msg.actuators:
            for sensor in actuator.sensors:
                if sensor.sensor_id not in SENSOR_IDS:
                    continue

                expected = sensor.rows * sensor.cols * sensor.channels
                if len(sensor.data) != expected:
                    self.get_logger().warn(
                        f'{sensor.sensor_id}: data size mismatch '
                        f'(expected {expected}, got {len(sensor.data)})'
                    )
                    continue

                idx = SENSOR_IDS.index(sensor.sensor_id)
                row, col = divmod(idx, 2)
                ax = self.axes[row, col]
                matrix = np.array(sensor.data).reshape(sensor.rows, sensor.cols)

                threshold = 0.01
                masked_matrix = np.ma.masked_where(matrix < threshold, matrix)

                nonzero_values = matrix[matrix >= threshold]
                if len(nonzero_values) > 0:
                    vmax = np.percentile(nonzero_values, 95)
                    vmax = max(vmax, 0.05)
                else:
                    vmax = 0.1

                if self.images[sensor.sensor_id] is None:
                    cmap = cm.get_cmap('plasma')
                    cmap.set_bad(color='#2a2a2a')

                    im = ax.imshow(
                        masked_matrix, cmap=cmap,
                        vmin=threshold, vmax=vmax,
                        interpolation='nearest', origin='upper'
                    )
                    ax.set_xlabel(f'Column (0-{sensor.cols - 1})')
                    ax.set_ylabel(f'Row (0-{sensor.rows - 1})')
                    self.fig.colorbar(im, ax=ax, fraction=0.046)
                    self.images[sensor.sensor_id] = im
                    self.fig.tight_layout()
                else:
                    im = self.images[sensor.sensor_id]
                    im.set_data(masked_matrix)
                    im.set_clim(vmin=threshold, vmax=vmax)

                ax.set_title(
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
