#!/usr/bin/env python3
"""通过 pactl 控制系统音量, 通过 spd-say 进行 TTS 播报.

依赖: 系统命令 pactl (PulseAudio) 与 spd-say (speech-dispatcher).
   sudo apt install pulseaudio-utils speech-dispatcher

用法示例:
   python3 test_audio.py --text "你好, 世界" --volume 60
   python3 test_audio.py --demo
   python3 test_audio.py --beep --volume 30
"""

import argparse
import math
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path

DEFAULT_SINK = "@DEFAULT_SINK@"


def _run(cmd, check=True, capture=True):
    return subprocess.run(
        cmd,
        check=check,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )


def require_tool(name):
    if shutil.which(name) is None:
        raise RuntimeError(f"系统未找到命令: {name}")


def get_volume_percent():
    """读取默认 sink 当前音量百分比 (取左右声道平均)."""
    require_tool("pactl")
    out = _run(["pactl", "list", "sinks"]).stdout
    sink_blocks = out.split("Sink #")
    default = _run(["pactl", "info"]).stdout
    m = re.search(r"Default Sink:\s*(\S+)", default)
    target_name = m.group(1) if m else None

    for block in sink_blocks[1:]:
        name_m = re.search(r"Name:\s*(\S+)", block)
        if not name_m:
            continue
        if target_name and name_m.group(1) != target_name:
            continue
        vols = re.findall(r"(\d+)%", re.search(r"Volume:.*", block).group(0))
        if vols:
            nums = [int(v) for v in vols[:2]]
            return sum(nums) // len(nums)
    raise RuntimeError("无法解析当前音量")


def set_volume_percent(percent):
    """设置默认 sink 音量, 范围 0-150."""
    require_tool("pactl")
    percent = max(0, min(150, int(percent)))
    _run(["pactl", "set-sink-mute", DEFAULT_SINK, "0"], check=False)
    _run(["pactl", "set-sink-volume", DEFAULT_SINK, f"{percent}%"])
    return percent


def speak(text, lang="zh", wait=True):
    """使用 spd-say 播报文本. wait=True 表示阻塞直到播完."""
    require_tool("spd-say")
    cmd = ["spd-say", "-l", lang, "-o", "espeak-ng"]
    if wait:
        cmd.append("-w")
    cmd.append(text)
    _run(cmd, capture=False)


def make_beep_wav(path, freq=440.0, duration=0.6, sample_rate=22050):
    """生成一个简单的正弦波 wav 文件."""
    n_frames = int(duration * sample_rate)
    amp = 0.5 * 32767
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        for i in range(n_frames):
            # 加入淡入淡出避免爆音
            env = min(1.0, i / 500, (n_frames - i) / 500)
            sample = int(amp * env * math.sin(2 * math.pi * freq * i / sample_rate))
            w.writeframesraw(struct.pack("<h", sample))


def play_beep(freq=440.0, duration=0.6):
    """播放一个蜂鸣音, 使用 paplay 优先, 退化到 aplay."""
    player = shutil.which("paplay") or shutil.which("aplay")
    if player is None:
        raise RuntimeError("未找到 paplay 或 aplay")
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        wav_path = Path(f.name)
    try:
        make_beep_wav(wav_path, freq=freq, duration=duration)
        _run([player, str(wav_path)], capture=False)
    finally:
        wav_path.unlink(missing_ok=True)


def run_demo(text, levels=(20, 50, 90)):
    """逐级调节音量并播报相同内容, 用于直观感受音量变化."""
    original = get_volume_percent()
    print(f"原始音量: {original}%")
    try:
        for v in levels:
            set_volume_percent(v)
            print(f"-> 音量 {v}%, 播报: {text!r}")
            speak(text)
            time.sleep(0.4)
    finally:
        set_volume_percent(original)
        print(f"恢复音量: {original}%")


def parse_args():
    p = argparse.ArgumentParser(description="系统音量调节 + 语音播报测试脚本")
    p.add_argument("--text", default="你好，这是一段语音测试。",
                   help="要播报的文字内容")
    p.add_argument("--lang", default="zh", help="语音语言 (zh, en, ...)")
    p.add_argument("--volume", type=int, default=None,
                   help="设置系统音量百分比 (0-150)")
    p.add_argument("--get-volume", action="store_true",
                   help="只读取当前音量并退出")
    p.add_argument("--beep", action="store_true",
                   help="播放正弦蜂鸣音而不是文字")
    p.add_argument("--freq", type=float, default=440.0, help="蜂鸣频率 Hz")
    p.add_argument("--duration", type=float, default=0.6, help="蜂鸣时长 s")
    p.add_argument("--demo", action="store_true",
                   help="演示模式: 在 20%/50%/90% 三档音量下播报相同内容")
    return p.parse_args()


def main():
    args = parse_args()

    if args.get_volume:
        print(f"{get_volume_percent()}%")
        return 0

    if args.demo:
        run_demo(args.text)
        return 0

    if args.volume is not None:
        v = set_volume_percent(args.volume)
        print(f"音量已设置为 {v}%")

    if args.beep:
        play_beep(freq=args.freq, duration=args.duration)
    else:
        speak(args.text, lang=args.lang)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except subprocess.CalledProcessError as e:
        print(f"命令执行失败: {' '.join(e.cmd)}\n{e.stderr}", file=sys.stderr)
        sys.exit(1)
    except RuntimeError as e:
        print(f"错误: {e}", file=sys.stderr)
        sys.exit(1)
