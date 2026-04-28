"""
华威科触觉传感器上位机
基于 tkinter 的图形界面工具
"""

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import serial
import serial.tools.list_ports
import struct
import threading
import time
import numpy as np
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from HIT_Tactile_Protocol import HIT_Tactile_Protocol, FrameMode, OpType, Frame
from sensor_mapping import SensorMapping

COMMANDS = {
    "读取设备信息": {"channel": 0x01, "op": OpType.GET, "payload": b'\x01'},
    "获取传感器数据": {"channel": 0x12, "op": OpType.GET, "payload": b'\x01'},
    "归零校准": {"channel": 0x07, "op": OpType.PUT, "payload": b'\x01\x01'},
    "设置设备地址": {"channel": 0x09, "op": OpType.PUT, "payload": None},
}

BAUDRATES = [921600, 115200, 57600, 38400, 19200, 9600]


class SensorGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("华威科触觉传感器上位机")
        self.root.geometry("1100x720")
        self.root.minsize(1000, 650)

        self.ser = None
        self.protocol = HIT_Tactile_Protocol(FrameMode.MASTER_SLAVE)
        self.mapping = SensorMapping("foot")
        self.pending_tx_bytes = None

        self._continuous_sending = False
        self._send_thread = None
        self._stop_event = threading.Event()

        self._device_info_cache = {}

        self._build_ui()
        self.scan_ports()

    # ── UI 构建 ──────────────────────────────────────────────

    def _build_ui(self):
        self.root.columnconfigure(0, weight=0)
        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(0, weight=1)

        left = ttk.Frame(self.root, padding=8)
        left.grid(row=0, column=0, sticky="nsew")

        right = ttk.Notebook(self.root)
        right.grid(row=0, column=1, sticky="nsew", padx=(4, 8), pady=8)

        self._build_left_panel(left)
        self._build_right_panel(right)

    def _build_left_panel(self, parent):
        row = 0

        # ── 串口设置 ──
        grp = ttk.LabelFrame(parent, text="串口设置", padding=6)
        grp.grid(row=row, column=0, sticky="ew", pady=(0, 6)); row += 1

        ttk.Label(grp, text="串口:").grid(row=0, column=0, sticky="w")
        self.port_var = tk.StringVar()
        self.port_cb = ttk.Combobox(grp, textvariable=self.port_var, width=18, state="readonly")
        self.port_cb.grid(row=0, column=1, padx=4)
        ttk.Button(grp, text="扫描", width=5, command=self.scan_ports).grid(row=0, column=2)

        ttk.Label(grp, text="波特率:").grid(row=1, column=0, sticky="w", pady=(4, 0))
        self.baud_var = tk.StringVar(value=str(BAUDRATES[0]))
        ttk.Combobox(grp, textvariable=self.baud_var, values=[str(b) for b in BAUDRATES],
                      width=18, state="readonly").grid(row=1, column=1, padx=4, pady=(4, 0))

        self.conn_btn = ttk.Button(grp, text="打开串口", command=self.toggle_serial)
        self.conn_btn.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(6, 0))

        # ── 指令设置 ──
        grp2 = ttk.LabelFrame(parent, text="指令设置", padding=6)
        grp2.grid(row=row, column=0, sticky="ew", pady=(0, 6)); row += 1

        ttk.Label(grp2, text="指令:").grid(row=0, column=0, sticky="w")
        self.cmd_var = tk.StringVar()
        cmd_cb = ttk.Combobox(grp2, textvariable=self.cmd_var,
                              values=list(COMMANDS.keys()), width=18, state="readonly")
        cmd_cb.grid(row=0, column=1, columnspan=2, padx=4)
        cmd_cb.bind("<<ComboboxSelected>>", self._on_cmd_changed)

        ttk.Label(grp2, text="设备ID:").grid(row=1, column=0, sticky="w", pady=(4, 0))
        self.devid_var = tk.StringVar(value="1")
        ttk.Entry(grp2, textvariable=self.devid_var, width=20).grid(row=1, column=1, columnspan=2, padx=4, pady=(4, 0))

        ttk.Label(grp2, text="目标地址:").grid(row=2, column=0, sticky="w", pady=(4, 0))
        self.target_var = tk.StringVar()
        self.target_entry = ttk.Entry(grp2, textvariable=self.target_var, width=20, state="disabled")
        self.target_entry.grid(row=2, column=1, columnspan=2, padx=4, pady=(4, 0))

        btn_frame = ttk.Frame(grp2)
        btn_frame.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(6, 0))
        ttk.Button(btn_frame, text="生成指令", command=self.generate_cmd).pack(side="left", expand=True, fill="x")
        self.send_btn = ttk.Button(btn_frame, text="发送", command=self.send_cmd)
        self.send_btn.pack(side="left", expand=True, fill="x", padx=(4, 0))

        cont_frame = ttk.Frame(grp2)
        cont_frame.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(4, 0))
        self.cont_var = tk.BooleanVar()
        ttk.Checkbutton(cont_frame, text="持续发送", variable=self.cont_var).pack(side="left")
        ttk.Label(cont_frame, text="频率(Hz):").pack(side="left", padx=(8, 2))
        self.freq_var = tk.StringVar(value="30")
        ttk.Entry(cont_frame, textvariable=self.freq_var, width=6).pack(side="left")

        # ── 报文显示 ──
        grp3 = ttk.LabelFrame(parent, text="报文", padding=6)
        grp3.grid(row=row, column=0, sticky="nsew", pady=(0, 0)); row += 1
        parent.rowconfigure(row - 1, weight=1)

        self.log_text = scrolledtext.ScrolledText(grp3, width=36, height=18, font=("Consolas", 9))
        self.log_text.pack(fill="both", expand=True)

    def _build_right_panel(self, notebook):
        # ── 设备信息页 ──
        info_frame = ttk.Frame(notebook, padding=8)
        notebook.add(info_frame, text="设备信息")

        self.info_text = scrolledtext.ScrolledText(info_frame, font=("Consolas", 10), state="disabled")
        self.info_text.pack(fill="both", expand=True)

        # ── 热力图页 ──
        heat_frame = ttk.Frame(notebook, padding=8)
        notebook.add(heat_frame, text="传感器热力图")

        self.fig = Figure(figsize=(5, 6), dpi=100)
        self.ax = self.fig.add_subplot(111)
        self.canvas = FigureCanvasTkAgg(self.fig, master=heat_frame)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)
        self._init_heatmap()

        self.notebook = notebook

    def _init_heatmap(self):
        rows, cols = self.mapping.get_grid_shape()
        self.grid_data = np.zeros((rows, cols), dtype=np.float32)
        mask = self.mapping.get_active_mask()
        display = np.ma.array(self.grid_data, mask=~mask)
        self.heatmap_img = self.ax.imshow(display, cmap="YlOrRd", interpolation="nearest",
                                          vmin=0, vmax=400, aspect="equal")
        self.fig.colorbar(self.heatmap_img, ax=self.ax, shrink=0.8, label="Pressure")
        self.ax.set_title("Tactile Sensor Heatmap")
        self.ax.set_xlabel("Col")
        self.ax.set_ylabel("Row")
        self.canvas.draw()

    # ── 串口操作 ──────────────────────────────────────────────

    def scan_ports(self):
        ports = serial.tools.list_ports.comports()
        ch340 = [p for p in ports if "CH340" in p.description.upper()]
        if ch340:
            self.port_cb["values"] = [f"{p.device} - {p.description}" for p in ch340]
        else:
            self.port_cb["values"] = [f"{p.device} - {p.description}" for p in ports]
        if self.port_cb["values"]:
            self.port_cb.current(0)
        self._log("扫描完成，" + (f"找到 {len(ch340)} 个 CH340 设备" if ch340 else f"共 {len(ports)} 个串口"))

    def toggle_serial(self):
        if self.ser and self.ser.is_open:
            self.ser.close()
            self.ser = None
            self.conn_btn.config(text="打开串口")
            self._log("串口已关闭")
        else:
            port_str = self.port_var.get()
            if not port_str:
                messagebox.showwarning("提示", "请先选择串口")
                return
            port = port_str.split(" - ")[0].strip()
            baud = int(self.baud_var.get())
            try:
                self.ser = serial.Serial(port, baud, timeout=0.2)
                self.conn_btn.config(text="关闭串口")
                self._log(f"已打开 {port} @ {baud}")
            except Exception as e:
                messagebox.showerror("错误", f"打开串口失败:\n{e}")

    # ── 指令生成与发送 ────────────────────────────────────────

    def _on_cmd_changed(self, _event=None):
        if self.cmd_var.get() == "设置设备地址":
            self.target_entry.config(state="normal")
        else:
            self.target_entry.config(state="disabled")
            self.target_var.set("")

    def generate_cmd(self):
        cmd_name = self.cmd_var.get()
        if not cmd_name:
            messagebox.showwarning("提示", "请选择指令")
            return

        try:
            dev_id = int(self.devid_var.get())
        except ValueError:
            messagebox.showwarning("提示", "设备ID必须为整数")
            return

        cmd_cfg = COMMANDS[cmd_name]
        frame = Frame(channel=cmd_cfg["channel"], device_id=dev_id)
        frame.op_type = cmd_cfg["op"]

        if cmd_name == "设置设备地址":
            try:
                target = int(self.target_var.get())
            except ValueError:
                messagebox.showwarning("提示", "目标地址必须为整数")
                return
            frame.device_id = 0
            frame.payload = struct.pack('BB', 0x04, target)
        else:
            frame.payload = cmd_cfg["payload"]

        raw = self.protocol.encode(frame)
        self.pending_tx_bytes = raw
        hex_str = " ".join(f"{b:02X}" for b in raw)
        self._log(f"[TX 生成] {cmd_name}\n{hex_str}")

    def send_cmd(self):
        if not self.ser or not self.ser.is_open:
            messagebox.showwarning("提示", "请先打开串口")
            return
        if self.pending_tx_bytes is None:
            messagebox.showwarning("提示", "请先生成指令")
            return

        if self._continuous_sending:
            self._stop_continuous()
        elif self.cont_var.get():
            self._start_continuous()
        elif self.cmd_var.get() == "读取设备信息":
            threading.Thread(target=self._query_all_device_info, daemon=True).start()
        else:
            threading.Thread(target=self._send_and_recv, daemon=True).start()

    def _start_continuous(self):
        try:
            freq = float(self.freq_var.get())
            if freq <= 0 or freq > 1000:
                messagebox.showwarning("提示", "频率范围: 0.1 ~ 1000 Hz")
                return
        except ValueError:
            messagebox.showwarning("提示", "频率必须为数字")
            return

        self._continuous_sending = True
        self._stop_event.clear()
        self.send_btn.config(text="发送ing")
        self._send_thread = threading.Thread(target=self._continuous_loop, args=(freq,), daemon=True)
        self._send_thread.start()
        self._log(f"[持续发送] 已启动，频率 {freq} Hz")

    def _stop_continuous(self):
        self._continuous_sending = False
        self._stop_event.set()
        if self._send_thread:
            self._send_thread.join(timeout=1.0)
        self.send_btn.config(text="发送")
        self.cont_var.set(False)
        self._log("[持续发送] 已停止")

    def _continuous_loop(self, freq: float):
        interval = 1.0 / freq
        while not self._stop_event.is_set():
            try:
                if self.ser and self.ser.is_open and self.pending_tx_bytes:
                    self.ser.write(self.pending_tx_bytes)
                    resp = self.ser.read(4096)
                    if resp:
                        self.root.after(0, self._parse_response, resp)
            except Exception as e:
                self.root.after(0, self._log, f"[持续发送错误] {e}")
                break
            self._stop_event.wait(interval)

    def _send_and_recv(self):
        try:
            self.ser.write(self.pending_tx_bytes)
            hex_tx = " ".join(f"{b:02X}" for b in self.pending_tx_bytes)
            self.root.after(0, self._log, f"[TX 发送] {hex_tx}")

            resp = self.ser.read(4096)
            if not resp:
                self.root.after(0, self._log, "[RX] 无响应")
                return

            hex_rx = " ".join(f"{b:02X}" for b in resp)
            self.root.after(0, self._log, f"[RX] {hex_rx}")
            self.root.after(0, self._parse_response, resp)
        except Exception as e:
            self.root.after(0, self._log, f"[错误] {e}")

    def _query_all_device_info(self):
        """查询所有设备信息属性 (CMD 0x01-0x06)"""
        try:
            dev_id = int(self.devid_var.get())
        except ValueError:
            self.root.after(0, lambda: messagebox.showwarning("提示", "设备ID必须为整数"))
            return

        self._device_info_cache.clear()
        self.root.after(0, self._log, "[设备信息] 开始查询...")

        for cmd in [0x01, 0x02, 0x03, 0x04, 0x05, 0x06]:
            try:
                frame = Frame(channel=0x01, device_id=dev_id)
                frame.op_type = OpType.GET
                frame.payload = struct.pack('B', cmd)
                tx_bytes = self.protocol.encode(frame)

                self.ser.write(tx_bytes)
                time.sleep(0.05)

                resp = self.ser.read(4096)
                if resp:
                    frames = self.protocol.find_frames(resp)
                    if frames:
                        _, resp_frame = frames[0]
                        self._device_info_cache[cmd] = resp_frame.payload

            except Exception as e:
                self.root.after(0, self._log, f"[设备信息] CMD 0x{cmd:02X} 查询失败: {e}")

        self.root.after(0, self._display_device_info)

    def _display_device_info(self):
        """汇总显示所有设备信息"""
        info_lines = [
            "═══ 设备信息 ═══",
            f"设备ID: {self.devid_var.get()}",
            "",
        ]

        # CMD 0x01: VERSION
        if 0x01 in self._device_info_cache:
            payload = self._device_info_cache[0x01]
            if len(payload) >= 6:
                major, minor = payload[0], payload[1]
                patch = struct.unpack('<I', payload[2:6])[0]
                info_lines.append(f"固件版本: {major}.{minor}.{patch}")
            else:
                version_str = payload.split(b'\x00')[0].decode('utf-8', errors='ignore')
                info_lines.append(f"固件版本: {version_str}")

        # CMD 0x02: WHISPER
        if 0x02 in self._device_info_cache:
            payload = self._device_info_cache[0x02]
            if len(payload) >= 6:
                major, minor = payload[0], payload[1]
                patch = struct.unpack('<I', payload[2:6])[0]
                info_lines.append(f"协议版本: {major}.{minor}.{patch}")

        # CMD 0x03: NUMBER + RESOLUTION + FORMAT + PHYSICAL_SIZE + SAR
        if 0x03 in self._device_info_cache:
            payload = self._device_info_cache[0x03]
            idx = 0
            if idx + 1 <= len(payload):
                num = payload[idx]
                idx += 1
                info_lines.append(f"传感器数量: {num}")

                if idx + 4 * num <= len(payload):
                    for i in range(num):
                        w = struct.unpack('<H', payload[idx:idx+2])[0]
                        h = struct.unpack('<H', payload[idx+2:idx+4])[0]
                        info_lines.append(f"  传感器{i+1} 分辨率: {w}×{h}")
                        idx += 4

                if idx + 1 <= len(payload):
                    fmt = payload[idx]
                    info_lines.append(f"数据格式: 0x{fmt:02X}")
                    idx += 1

                if idx + 4 <= len(payload):
                    pw = struct.unpack('<H', payload[idx:idx+2])[0]
                    ph = struct.unpack('<H', payload[idx+2:idx+4])[0]
                    info_lines.append(f"物理尺寸: {pw}×{ph} mm")
                    idx += 4

                if idx + 2 <= len(payload):
                    sar_w, sar_h = payload[idx], payload[idx+1]
                    info_lines.append(f"宽高比: {sar_w}:{sar_h}")

        # CMD 0x04: RANGE
        if 0x04 in self._device_info_cache:
            payload = self._device_info_cache[0x04]
            if len(payload) >= 8:
                min_val = struct.unpack('<f', payload[0:4])[0]
                max_val = struct.unpack('<f', payload[4:8])[0]
                info_lines.append(f"量值范围: {min_val:.2f} ~ {max_val:.2f}")

        # CMD 0x05: SERIAL_NUMBER
        if 0x05 in self._device_info_cache:
            payload = self._device_info_cache[0x05]
            sn = payload.split(b'\x00')[0].decode('utf-8', errors='ignore')
            if sn:
                info_lines.append(f"序列号: {sn}")

        # CMD 0x06: ADDRESS
        if 0x06 in self._device_info_cache:
            payload = self._device_info_cache[0x06]
            if len(payload) >= 1:
                addr = payload[0]
                info_lines.append(f"设备地址: 0x{addr:02X}")

        text = "\n".join(info_lines)
        self.info_text.config(state="normal")
        self.info_text.delete("1.0", tk.END)
        self.info_text.insert(tk.END, text)
        self.info_text.config(state="disabled")
        self.notebook.select(0)
        self._log("[设备信息] 查询完成")

    # ── 响应解析 ──────────────────────────────────────────────

    def _parse_response(self, data: bytes):
        cmd_name = self.cmd_var.get()
        try:
            frames = self.protocol.find_frames(data)
            if not frames:
                self._log("[解析] 未找到有效帧")
                return

            for _offset, frame in frames:
                if cmd_name == "获取传感器数据":
                    self._show_sensor_data(frame)
                elif cmd_name == "归零校准":
                    self._log("[解析] 归零校准响应已收到")
                elif cmd_name == "设置设备地址":
                    self._log("[解析] 设置地址响应已收到")
        except Exception as e:
            self._log(f"[解析错误] {e}")

    def _show_sensor_data(self, frame: Frame):
        try:
            sensor_data = self.protocol.parse_sensor_data(frame.payload)
            flat = np.array(sensor_data.to_flat_list(), dtype=np.float32)

            expected = self.mapping.get_sensor_count()
            if len(flat) >= expected:
                grid = self.mapping.map_data_to_grid(flat[:expected])
            else:
                rows, cols = sensor_data.rows, sensor_data.cols
                grid = flat.reshape(rows, cols) if rows * cols == len(flat) else flat.reshape(-1, 1)

            self._update_heatmap(grid)
            self.notebook.select(1)
        except Exception as e:
            self._log(f"[解析] 传感器数据解析失败: {e}")

    def _update_heatmap(self, grid: np.ndarray):
        mask = np.zeros_like(grid, dtype=bool)
        if grid.shape == self.mapping.get_grid_shape():
            mask = ~self.mapping.get_active_mask()
        display = np.ma.array(grid, mask=mask)

        self.heatmap_img.set_data(display)
        self.ax.set_title("Tactile Sensor Heatmap")
        self.canvas.draw_idle()

    # ── 工具方法 ──────────────────────────────────────────────

    def _log(self, msg: str):
        self.log_text.insert(tk.END, msg + "\n")
        self.log_text.see(tk.END)


def main():
    root = tk.Tk()
    SensorGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
