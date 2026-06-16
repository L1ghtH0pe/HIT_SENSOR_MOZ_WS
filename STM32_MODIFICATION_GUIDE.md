# 下位机（STM32）改动指南 - 力度引导反馈

## 概述

上位机现在会发送三阶段编码的 flag（0-255）：
- **0-84**：太弱阶段（sum < 80）
- **85-170**：目标阶段（80 ≤ sum ≤ 120），中心点127
- **171-255**：太强阶段（sum > 120）

下位机需要根据 flag 范围实现：
1. **差异化的红→黄→绿→黄→红颜色渐变**
2. **三种不同音效的蜂鸣提示**

---

## 文件位置

`/home/mxz/Desktop/HIT_BEEP_LED_MCU2.0/bsp/UserMiddlewares/source/UserFreertos.c`

---

## 需要修改的部分

### 1. 添加阶段定义（文件开头宏定义区）

在现有的 `#define` 宏定义区（第7-19行附近）添加：

```c
// 三阶段力度引导编码边界
#define STAGE_WEAK_MAX    84   // 太弱阶段上限
#define STAGE_TARGET_MIN  85   // 目标阶段下限
#define STAGE_TARGET_MID  127  // 目标阶段中心
#define STAGE_TARGET_MAX  170  // 目标阶段上限
#define STAGE_STRONG_MIN  171  // 太强阶段下限

// 颜色参数
#define COLOR_WEAK_RED      180   // 太弱阶段：暗红/橙红
#define COLOR_STRONG_RED    255   // 太强阶段：亮红
#define COLOR_TARGET_GREEN  255   // 目标阶段：绿色亮度
#define COLOR_YELLOW_RED    150   // 黄色过渡的红分量
```

---

### 2. 修改颜色映射函数

**函数名**：`LEDTask_GetForceColor(uint8_t level, uint8_t *red, uint8_t *green, uint8_t *blue)`

**当前位置**：第84-106行

**完整替换为**：

```c
static void LEDTask_GetForceColor(uint8_t level, uint8_t *red, uint8_t *green, uint8_t *blue)
{
  uint32_t ratio;
  
  *blue = 0U;  // 全程不用蓝色

  if (level == 0U)
  {
    // 完全静止，灭灯
    *red = 0U;
    *green = 0U;
  }
  else if (level <= STAGE_WEAK_MAX)
  {
    // 阶段1：太弱 (0-84)
    // 颜色：暗红 → 橙黄
    // 策略：暗红色打底，缓慢增加绿分量
    ratio = ((uint32_t)level * 255U) / STAGE_WEAK_MAX;
    *red = COLOR_WEAK_RED;  // 暗红（180，不是满255）
    *green = (uint8_t)((ratio * 100U) / 255U);  // 缓慢增绿，最多到100
  }
  else if (level <= STAGE_TARGET_MAX)
  {
    // 阶段2：目标区间 (85-170)
    // 颜色：黄 → 绿 → 黄（中心点127最绿）
    if (level <= STAGE_TARGET_MID)
    {
      // 85-127：黄 → 绿
      ratio = ((uint32_t)(level - STAGE_TARGET_MIN) * 255U) / 
              (STAGE_TARGET_MID - STAGE_TARGET_MIN);
      *red = (uint8_t)(COLOR_YELLOW_RED - ((ratio * COLOR_YELLOW_RED) / 255U));  // 150→0
      *green = COLOR_TARGET_GREEN;  // 满绿255
    }
    else
    {
      // 128-170：绿 → 黄
      ratio = ((uint32_t)(level - STAGE_TARGET_MID) * 255U) / 
              (STAGE_TARGET_MAX - STAGE_TARGET_MID);
      *red = (uint8_t)((ratio * COLOR_YELLOW_RED) / 255U);  // 0→150
      *green = COLOR_TARGET_GREEN;  // 满绿255
    }
  }
  else
  {
    // 阶段3：太强 (171-255)
    // 颜色：黄 → 亮红
    // 策略：满红打底，递减绿分量
    ratio = ((uint32_t)(level - STAGE_STRONG_MIN) * 255U) / 
            (255U - STAGE_STRONG_MIN);
    *red = COLOR_STRONG_RED;  // 满红255
    *green = (uint8_t)(200U - ((ratio * 200U) / 255U));  // 200→0（从亮黄到纯红）
  }
}
```

**视觉效果说明**：
- **太弱（0-84）**：暗红色（180,0,0）→ 橙色（180,100,0）
- **目标左半（85-127）**：黄色（150,255,0）→ 纯绿（0,255,0）
- **目标右半（128-170）**：纯绿（0,255,0）→ 黄色（150,255,0）
- **太强（171-255）**：亮黄（255,200,0）→ 纯红（255,0,0）

**前后红色的差异**：
- 前红（太弱）：暗、偏橙，RGB=(180,0-100,0)
- 后红（太强）：亮、纯红，RGB=(255,0-200,0) → (255,0,0)

---

### 3. 修改蜂鸣器控制函数

**函数名**：`LEDTask_UpdateBeep(uint8_t level)`

**当前位置**：第162-190行附近

**需要改的地方**：根据阶段控制**间隔（interval）和音调（频率）**。

**修改后的逻辑**：

```c
static void LEDTask_UpdateBeep(uint8_t level)
{
  static uint32_t beep_elapsed = 0U;
  static uint8_t was_active = 0U;
  uint32_t beep_interval;
  uint16_t beep_period;

  // 全程都有提示音，但根据阶段调整节奏和音调
  if (level == 0U)
  {
    // 完全静止，不响
    was_active = 0U;
    beep_elapsed = 0U;
    return;
  }

  // 根据阶段决定间隔和音调
  if (level <= STAGE_WEAK_MAX)
  {
    // 阶段1：太弱
    // 低频慢节奏（提示：力度不够）
    beep_interval = 800U;   // 慢（0.8秒一次）
    beep_period = T_L3;     // 低音（假设你的Beep.h有定义T_L3、T_M3、T_H3等）
  }
  else if (level <= STAGE_TARGET_MAX)
  {
    // 阶段2：目标区间
    // 中频中速（提示：在理想区间内）
    beep_interval = 500U;   // 中速（0.5秒一次）
    beep_period = T_M5;     // 中音
  }
  else
  {
    // 阶段3：太强
    // 高频快节奏（警告：力度过大）
    beep_interval = 250U;   // 急促（0.25秒一次）
    beep_period = T_H6;     // 高音
  }

  // 间隔控制逻辑（保留原有的 was_active 机制）
  if (was_active == 0U)
  {
    beep_elapsed = beep_interval;  // 首次立即触发
    was_active = 1U;
  }
  else
  {
    beep_elapsed += LED_TASK_UPDATE_MS;
  }

  if (beep_elapsed >= beep_interval)
  {
    // 发声（调用你的 Beep 驱动，假设是 Beep_SetPeriod + Beep_Trigger）
    Beep_SetPeriod(beep_period);  // 根据你的Beep驱动API调整
    Beep_Start(100);              // 响100ms，根据实际API调整
    beep_elapsed = 0U;
  }
}
```

**音调说明**：
- 假设你的 `Beep.h` 定义了音符宏（如 `T_L3`、`T_M5`、`T_H6` 等，分别对应低、中、高音）
- 如果没有，可以用 PWM 周期值，比如：
  - 低音：2000（周期长，频率低）
  - 中音：1000
  - 高音：500（周期短，频率高）

**你需要根据实际的 Beep 驱动 API 调整**：
- 查看 `/home/mxz/Desktop/HIT_BEEP_LED_MCU2.0/bsp/Beep/include/Beep.h`
- 找到设置音调和触发蜂鸣的函数名
- 替换上面代码中的 `Beep_SetPeriod()` 和 `Beep_Start()`

---

## 编译和烧录

1. 打开 Keil 工程：`/home/mxz/Desktop/HIT_BEEP_LED_MCU2.0/MDK-ARM/*.uvprojx`
2. 编译（Build）
3. 烧录到 STM32（ST-Link 或 USB DFU）

---

## 测试验证

### 测试步骤

用夹爪夹纸杯，观察：

| sum 范围 | 预期 flag | 预期颜色 | 预期音效 |
|---------|-----------|---------|---------|
| 0-40 | 0-42 | 暗红 | 慢+低频 |
| 40-79 | 42-84 | 暗红→橙 | 慢+低频 |
| 80-100 | 85-127 | 黄→绿 | 中速+中频 |
| 100-120 | 127-170 | 绿→黄 | 中速+中频 |
| 120-160 | 171-213 | 黄→亮红 | 快+高频 |
| 160+ | 213-255 | 亮红 | 快+高频 |

### 调试提示

1. **颜色不够明显**：
   - 调整 `COLOR_WEAK_RED`（太弱的红）更暗/更亮
   - 调整 `COLOR_YELLOW_RED`（黄色的红分量）让黄色更明显

2. **音调不对**：
   - 检查 `Beep.h` 中的音符定义
   - 调整 `beep_period` 的具体值

3. **间隔太快/太慢**：
   - 调整 `beep_interval` 的三个值（800/500/250）

---

## 参数微调建议

如果实测发现：
- **"太弱"阶段太敏感**（sum刚到50就判定太弱）→ 让上位机的 `TARGET_LOW` 降低（比如改成60）
- **"太强"阶段太晚触发**（sum到200还是绿色）→ 让上位机的 `TARGET_HIGH` 降低（比如改成100）

**上位机参数位置**：`tactile_feedback.py` 第288-291行：
```python
TARGET_CENTER = 100.0  # 目标中心
TARGET_RANGE = 20.0    # 范围±20
```

---

## Codex 提示词（如果需要）

如果你用 Codex 辅助修改，可以给它这个提示：

```
请修改 UserFreertos.c 中的 LEDTask_GetForceColor 和 LEDTask_UpdateBeep 函数。

需求：
1. level 编码为三阶段：0-84(太弱), 85-170(目标), 171-255(太强)
2. 颜色映射：
   - 太弱(0-84): 暗红(180,0,0)渐变到橙(180,100,0)
   - 目标(85-170): 黄(150,255,0)→绿(0,255,0)→黄(150,255,0)，中心点127最绿
   - 太强(171-255): 亮黄(255,200,0)渐变到纯红(255,0,0)
3. 蜂鸣器：
   - 太弱: 间隔800ms，低频(T_L3或周期2000)
   - 目标: 间隔500ms，中频(T_M5或周期1000)
   - 太强: 间隔250ms，高频(T_H6或周期500)

保留现有的 LED 渐变和心跳指示灯逻辑。
```

---

## 完成

改完后重新编译烧录，配合上位机的新代码测试即可。
