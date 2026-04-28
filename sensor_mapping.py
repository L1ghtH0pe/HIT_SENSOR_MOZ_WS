"""
触觉传感器映射配置
定义传感器数据索引到显示网格坐标的映射关系
"""

import numpy as np
from typing import List, Tuple


class SensorMapping:
    """传感器映射配置类"""

    def __init__(self, mapping_name: str = "default"):
        self.mapping_name = mapping_name
        self.grid_shape = (10, 8)  # 显示网格尺寸 (rows, cols)
        self.sensor_positions = []  # [(row, col), ...] 传感器在网格中的位置
        self._load_mapping(mapping_name)

    def _load_mapping(self, name: str):
        """加载映射配置"""
        if name == "default" or name == "foot":
            self._load_foot_mapping()
        elif name == "hand":
            self._load_hand_mapping()
        else:
            raise ValueError(f"未知的映射配置: {name}")

    def _load_foot_mapping(self):
        """足底传感器映射（根据图片）

        传感器数据顺序：19x2 矩阵，按行优先展平为38个点
        索引 0-37 依次映射到网格中的蓝色位置
        """
        # 根据图片中的蓝色位置，从上到下、从左到右定义映射
        # 格式: (row, col) - 注意行列从0开始
        self.sensor_positions = [
            # 第1行: 列4-5 (2个传感器)
            (0, 3), (0, 4),

            # 第2行: 列4-5 (2个传感器)
            (1, 3), (1, 4),

            # 第3行: 列3-6 (4个传感器)
            (2, 2), (2, 3), (2, 4), (2, 5),

            # 第4行: 列3-6 (4个传感器)
            (3, 2), (3, 3), (3, 4), (3, 5),

            # 第5行: 列3-6 (4个传感器)
            (4, 2), (4, 3), (4, 4), (4, 5),

            # 第6行: 列2-7 (6个传感器)
            (5, 1), (5, 2), (5, 3), (5, 4), (5, 5), (5, 6),

            # 第7行: 列2-7 (6个传感器)
            (6, 1), (6, 2), (6, 3), (6, 4), (6, 5), (6, 6),

            # 第8行: 列1, 列7 (2个传感器)
            (7, 1), (7, 6),

            # 第9行: 列1-2, 列7-8 (4个传感器)
            (8, 0), (8, 1), (8, 6), (8, 7),

            # 第10行: 列1-2, 列7-8 (4个传感器)
            (9, 0), (9, 1), (9, 6), (9, 7),
        ]

        # 验证传感器数量
        assert len(self.sensor_positions) == 38, \
            f"传感器数量不匹配: 期望38个, 实际{len(self.sensor_positions)}个"

    def _load_hand_mapping(self):
        """手掌传感器映射（示例，可自定义）"""
        # 这里可以定义不同的映射配置
        self.grid_shape = (8, 8)
        self.sensor_positions = [
            # 自定义手掌形状的映射...
        ]

    def get_grid_shape(self) -> Tuple[int, int]:
        """获取显示网格尺寸"""
        return self.grid_shape

    def get_sensor_count(self) -> int:
        """获取传感器数量"""
        return len(self.sensor_positions)

    def map_data_to_grid(self, sensor_data: np.ndarray) -> np.ndarray:
        """将传感器数据映射到显示网格

        Args:
            sensor_data: 传感器数据，形状为 (rows, cols) 或一维数组

        Returns:
            grid_data: 显示网格数据，形状为 self.grid_shape
        """
        # 展平传感器数据
        if sensor_data.ndim == 2:
            flat_data = sensor_data.flatten()
        else:
            flat_data = sensor_data

        # 验证数据长度
        if len(flat_data) != len(self.sensor_positions):
            raise ValueError(
                f"传感器数据长度不匹配: 期望{len(self.sensor_positions)}, "
                f"实际{len(flat_data)}"
            )

        # 创建网格数组，初始化为 NaN（表示无传感器）
        grid_data = np.zeros(self.grid_shape, dtype=np.float32)

        # 将传感器数据映射到网格位置
        for sensor_idx, (row, col) in enumerate(self.sensor_positions):
            grid_data[row, col] = flat_data[sensor_idx]

        return grid_data

    def get_active_mask(self) -> np.ndarray:
        """获取有效传感器位置的mask

        Returns:
            mask: 布尔数组，True表示该位置有传感器
        """
        mask = np.zeros(self.grid_shape, dtype=bool)
        for row, col in self.sensor_positions:
            mask[row, col] = True
        return mask

    def save_mapping(self, filename: str):
        """保存映射配置到文件"""
        import json
        config = {
            'name': self.mapping_name,
            'grid_shape': self.grid_shape,
            'sensor_positions': self.sensor_positions
        }
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        print(f"映射配置已保存到: {filename}")

    @classmethod
    def load_from_file(cls, filename: str):
        """从文件加载映射配置"""
        import json
        with open(filename, 'r', encoding='utf-8') as f:
            config = json.load(f)

        mapping = cls.__new__(cls)
        mapping.mapping_name = config['name']
        mapping.grid_shape = tuple(config['grid_shape'])
        mapping.sensor_positions = [tuple(pos) for pos in config['sensor_positions']]
        return mapping


# 预定义映射配置
AVAILABLE_MAPPINGS = {
    'foot': '足底传感器映射（10x8网格，38个传感器）',
    'hand': '手掌传感器映射（自定义）',
}


def list_available_mappings():
    """列出可用的映射配置"""
    print("可用的映射配置:")
    for name, desc in AVAILABLE_MAPPINGS.items():
        print(f"  - {name}: {desc}")


if __name__ == '__main__':
    # 测试映射配置
    print("="*70)
    print("触觉传感器映射配置测试")
    print("="*70)

    # 创建足底映射
    mapping = SensorMapping("foot")
    print(f"\n映射名称: {mapping.mapping_name}")
    print(f"网格尺寸: {mapping.grid_shape}")
    print(f"传感器数量: {mapping.get_sensor_count()}")

    # 测试数据映射
    test_data = np.arange(38, dtype=np.float32)  # 0-37
    grid_data = mapping.map_data_to_grid(test_data)

    print(f"\n网格数据形状: {grid_data.shape}")
    print(f"有效传感器数: {np.sum(~np.isnan(grid_data))}")

    # 显示映射结果
    print("\n映射结果（传感器索引）:")
    for r in range(mapping.grid_shape[0]):
        row_str = f"行{r+1:2d}: "
        for c in range(mapping.grid_shape[1]):
            val = grid_data[r, c]
            if np.isnan(val):
                row_str += "  -- "
            else:
                row_str += f" {int(val):3d} "
        print(row_str)

    # 保存配置
    mapping.save_mapping('sensor_mapping_foot.json')

    # 测试加载
    loaded_mapping = SensorMapping.load_from_file('sensor_mapping_foot.json')
    print(f"\n从文件加载的映射: {loaded_mapping.mapping_name}")
