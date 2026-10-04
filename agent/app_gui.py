"""Focus Agent Desktop Application GUI.

Provides:
- Settings menu for jumping jack goal, connection mode, speaker output, and volume.
- Background sentinel operation (monitoring posture while minimized).
- Embedded live OpenCV camera preview with face/eye posture HUD.
- Fullscreen blocking overlay upon doomscroll detection.
"""

import sys
import os
import time
import threading
import logging
import tkinter as tk
from tkinter import ttk, messagebox
import queue
import cv2
import numpy as np
from PIL import Image, ImageTk

# Setup persistent logging
log_dir = os.path.join(os.getenv("APPDATA", "."), "FreeWiliFocusAgent")
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, "focus_agent.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] (%(name)s) %(message)s",
    handlers=[
        logging.FileHandler(log_file, encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("FocusAgentGUI")

from settings_manager import load_settings, save_settings
from freewili_client import FreeWiliClient, FreeWiliTelemetry
from doomscroll_detector import DoomscrollDetector
from audio_manager import AudioManager, SOUND_SWIVEL_NECK, SOUND_PENALTY_CLEARED
from overlay import PenaltyOverlay
from ui_effects import GradientButton, create_horizontal_gradient_image, create_vertical_gradient_image


class ScrollableFrame(tk.Frame):
    """Frosted Charcoal Scrollable Container with automatic mousewheel support."""

    def __init__(self, container, bg="#0D0E12", *args, **kwargs):
        super().__init__(container, bg=bg, *args, **kwargs)
        self.canvas = tk.Canvas(self, bg=bg, bd=0, highlightthickness=0)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.scrollable_window = tk.Frame(self.canvas, bg=bg)

        self.scrollable_window.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )

        self._window_id = self.canvas.create_window((0, 0), window=self.scrollable_window, anchor="nw")

        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")

        self.bind_all("<MouseWheel>", self._on_mousewheel)

    def _on_canvas_configure(self, event):
        self.canvas.itemconfig(self._window_id, width=event.width)

    def _on_mousewheel(self, event):
        if self.winfo_exists() and self.canvas.winfo_exists():
            bbox = self.canvas.bbox("all")
            if bbox and (bbox[3] - bbox[1] > self.canvas.winfo_height()):
                self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")


class FocusAgentApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Focus Agent - Discipline Sentinel")
        self.root.geometry("740x880")
        self.root.minsize(680, 720)
        self.root.configure(bg="#0D0E12")

        # Load saved settings
        self.settings = load_settings()
        logger.info(f"Loaded settings: {self.settings}")

        # Audio Manager (defaulting to user setting)
        self.audio = AudioManager(
            freewili_client=None,
            output_destination=self.settings.get("speaker_output", "laptop")
        )

        # Penalty Overlay
        self.overlay = PenaltyOverlay(self.root, on_emergency_unlock=self.reset_penalty_state)

        # FreeWili Client
        self.freewili = FreeWiliClient(on_telemetry=self.on_freewili_telemetry)
        self.audio.freewili = self.freewili

        # Sentinel State
        self.is_monitoring = False
        self.penalty_active = False
        self.penalty_start_jumps = 0
        self.jumps_in_penalty = 0
        self.last_reprimand_time = 0.0

        self.monitor_thread = None
        self.detector = None
        self.cap = None
        self.preview_active = True
        self.show_cam_preview = tk.BooleanVar(value=True)
        self._current_photo_image = None

        # Thread-safe queues
        self.preview_queue = queue.Queue(maxsize=1)
        self.event_queue = queue.Queue()

        # Build UI
        self._build_style()
        self._build_tabs()

        # Start thread-safe pollers on main thread
        self.root.after(30, self._poll_event_queue)
        self.root.after(30, self._poll_preview_queue)

        # Handle window close
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        # Apply settings on load
        self.update_freewili_connection(initial=True)

    def _build_style(self):
        style = ttk.Style(self.root)
        style.theme_use("clam")

        style.configure("TNotebook", background="#0D0E12", borderwidth=0)
        style.configure("TNotebook.Tab", background="#15171E", foreground="#8E94A5",
                        font=("Segoe UI", 10, "bold"), padding=[20, 8])
        style.map("TNotebook.Tab",
                  background=[("selected", "#222530")],
                  foreground=[("selected", "#EDEDF0")])

        style.configure("TFrame", background="#0D0E12")
        style.configure("Card.TFrame", background="#15171E", relief="solid", borderwidth=1)
        style.configure("TLabel", background="#0D0E12", foreground="#EDEDF0", font=("Segoe UI", 10))
        style.configure("Card.TLabel", background="#15171E", foreground="#EDEDF0")
        style.configure("Muted.TLabel", background="#15171E", foreground="#71717A", font=("Segoe UI", 9))
        style.configure("Header.TLabel", background="#15171E", foreground="#EDEDF0",
                        font=("Segoe UI", 12, "bold"))

        style.configure("Accent.TButton", font=("Segoe UI", 10, "bold"),
                        background="#1E222C", foreground="#EDEDF0", padding=8)
        style.map("Accent.TButton",
                  background=[("active", "#2A2F3D"), ("pressed", "#14161E")])

    def _build_tabs(self):
        # Frosted Charcoal Header Canvas
        hdr_canvas = tk.Canvas(self.root, height=64, bg="#0D0E12", bd=0, highlightthickness=0)
        hdr_canvas.pack(fill="x", side="top")

        # Frosted glass background & bottom highlight stroke
        self._hdr_bg_img = ImageTk.PhotoImage(
            create_horizontal_gradient_image(780, 64, "#0D0E12", "#161820", "#181A22")
        )
        self._hdr_line_img = ImageTk.PhotoImage(
            create_horizontal_gradient_image(780, 1, "#282B35", "#3A3F4E", "#282B35")
        )
        hdr_canvas.create_image(0, 0, image=self._hdr_bg_img, anchor="nw")
        hdr_canvas.create_image(0, 63, image=self._hdr_line_img, anchor="nw")

        title_lbl = tk.Label(
            hdr_canvas, text="FOCUS AGENT", font=("Segoe UI", 17, "bold"),
            fg="#EDEDF0", bg="#161820"
        )
        title_lbl.place(x=20, y=16)

        sub_lbl = tk.Label(
            hdr_canvas, text="// DISCIPLINE SENTINEL", font=("Segoe UI", 9, "bold"),
            fg="#71717A", bg="#161820"
        )
        sub_lbl.place(x=160, y=22)

        # Tab notebook
        notebook = ttk.Notebook(self.root)
        notebook.pack(expand=True, fill="both", padx=12, pady=10)

        self.tab_dash = ttk.Frame(notebook)
        self.tab_settings = ttk.Frame(notebook)

        notebook.add(self.tab_dash, text="  Dashboard  ")
        notebook.add(self.tab_settings, text="  Settings  ")

        self._build_dashboard_tab()
        self._build_settings_tab()

    # -------------------------------------------------------------
    # Dashboard Tab (Scrollable)
    # -------------------------------------------------------------
    def _build_dashboard_tab(self):
        self.dash_scroll = ScrollableFrame(self.tab_dash, bg="#0D0E12")
        self.dash_scroll.pack(fill="both", expand=True)
        content = self.dash_scroll.scrollable_window

        # Master Control Card (Frosted Charcoal)
        ctrl_card = tk.LabelFrame(content, text=" Sentinel Control ", font=("Segoe UI", 10, "bold"),
                                  bg="#15171E", fg="#EDEDF0", bd=1, relief="solid", padx=15, pady=12)
        ctrl_card.pack(fill="x", padx=10, pady=(8, 6))

        self.status_banner = tk.Label(
            ctrl_card,
            text="SENTINEL READY // CLICK 'START SENTINEL' TO ACTIVATE",
            font=("Segoe UI", 10, "bold"),
            bg="#181A22",
            fg="#A1A1AA",
            pady=8
        )
        self.status_banner.pack(fill="x", pady=(0, 10))

        btn_box = tk.Frame(ctrl_card, bg="#15171E")
        btn_box.pack(fill="x")

        self.start_btn = GradientButton(
            btn_box,
            text="▶   START SENTINEL",
            command=self.toggle_sentinel,
            width_px=220,
            height_px=42,
            color1="#1E222C",
            color2="#14161E",
            hover_color1="#2B303E",
            hover_color2="#1E222C",
            fg="#EDEDF0",
            corner_radius=6
        )
        self.start_btn.pack(side="left", expand=True, fill="x", padx=(0, 8))

        min_btn = tk.Button(
            btn_box,
            text="🗕   Minimize to Background",
            font=("Segoe UI", 10, "bold"),
            bg="#1C1E26",
            fg="#EDEDF0",
            activebackground="#262934",
            activeforeground="#FFFFFF",
            bd=1,
            relief="solid",
            padx=14,
            pady=9,
            command=self.minimize_to_background,
            cursor="hand2"
        )
        min_btn.pack(side="right", padx=(8, 0))

        # Checkbox: Camera window preview
        cam_chk = tk.Checkbutton(
            ctrl_card,
            text="Show Embedded Webcam HUD Preview",
            variable=self.show_cam_preview,
            command=self._on_cam_preview_toggle,
            font=("Segoe UI", 10),
            bg="#15171E",
            fg="#A1A1AA",
            selectcolor="#0D0E12",
            activebackground="#15171E",
            activeforeground="#EDEDF0"
        )
        cam_chk.pack(anchor="w", pady=(8, 0))

        # Camera Preview Frame (Embedded directly in GUI)
        self.cam_card = tk.LabelFrame(content, text=" Live Camera Posture Feed ",
                                      font=("Segoe UI", 10, "bold"),
                                      bg="#15171E", fg="#EDEDF0", bd=1, relief="solid", padx=10, pady=8)
        self.cam_card.pack(fill="x", padx=10, pady=(0, 6))

        self.cam_container = tk.Frame(self.cam_card, bg="#0D0E12", width=480, height=360)
        self.cam_container.pack(pady=4)
        self.cam_container.pack_propagate(False)

        self.cam_preview_label = tk.Label(
            self.cam_container,
            text="\n\nWebcam feed will appear here when Sentinel is started.\n(Live face & posture tracking)",
            font=("Segoe UI", 10),
            bg="#0D0E12",
            fg="#71717A",
        )
        self.cam_preview_label.pack(expand=True, fill="both")

        calib_btn = tk.Button(
            self.cam_card,
            text="🎯  Recalibrate Upright Baseline Posture",
            font=("Segoe UI", 9, "bold"),
            bg="#1C1E26",
            fg="#EDEDF0",
            activebackground="#262934",
            activeforeground="#FFFFFF",
            bd=1,
            relief="solid",
            pady=3,
            command=self.recalibrate_baseline,
            cursor="hand2"
        )
        calib_btn.pack(pady=(2, 4))

        # Live Telemetry Card
        telem_card = tk.LabelFrame(content, text=" FreeWili Live Telemetry & Discipline ",
                                   font=("Segoe UI", 10, "bold"),
                                   bg="#15171E", fg="#EDEDF0", bd=1, relief="solid", padx=15, pady=10)
        telem_card.pack(fill="both", expand=True, padx=10, pady=(0, 6))

        # Connection Row
        conn_row = tk.Frame(telem_card, bg="#15171E")
        conn_row.pack(fill="x", pady=2)

        tk.Label(conn_row, text="Hardware Link:", font=("Segoe UI", 10, "bold"),
                 bg="#15171E", fg="#71717A").pack(side="left")

        self.conn_badge = tk.Label(conn_row, text="INITIALIZING...", font=("Segoe UI", 9, "bold"),
                                   bg="#20222B", fg="#EDEDF0", padx=8, pady=2)
        self.conn_badge.pack(side="left", padx=10)

        # Reps Big Display
        reps_box = tk.Frame(telem_card, bg="#15171E")
        reps_box.pack(fill="x", pady=2)

        self.reps_display = tk.Label(
            reps_box,
            text=f"REPS: 0 / {self.settings.get('target_jumps', 10)}",
            font=("Segoe UI", 24, "bold"),
            fg="#EDEDF0",
            bg="#15171E"
        )
        self.reps_display.pack(anchor="center")

        # Rep Progress Bar (Canvas)
        self.dash_prog_canvas = tk.Canvas(
            telem_card,
            height=12,
            bg="#0D0E12",
            bd=0,
            highlightthickness=1,
            highlightbackground="#282B35",
        )
        self.dash_prog_canvas.pack(fill="x", padx=30, pady=(2, 6))
        self._dash_fill_id = self.dash_prog_canvas.create_rectangle(0, 0, 0, 12, fill="#EDEDF0", outline="")

        # Accelerometer State
        self.accel_info = tk.Label(
            telem_card,
            text="Motion: [ READY ] | G-Magnitude: 1.00g | Peak: 0.00g",
            font=("Consolas", 10),
            fg="#71717A",
            bg="#15171E"
        )
        self.accel_info.pack(pady=2)

        # Audio Output Status Row
        self.audio_dest_info = tk.Label(
            telem_card,
            text=f"Active Speaker: {self.settings.get('speaker_output', 'laptop').upper()} SPEAKER",
            font=("Segoe UI", 10),
            fg="#A1A1AA",
            bg="#15171E"
        )
        self.audio_dest_info.pack(pady=2)

        # Test Penalty Overlay Button
        test_frame = tk.Frame(content, bg="#0D0E12")
        test_frame.pack(fill="x", padx=10, pady=(0, 8))

        test_btn = tk.Button(
            test_frame,
            text="⚡   Test Penalty Screen & Audio Now",
            font=("Segoe UI", 10, "bold"),
            bg="#221417",
            fg="#EF4444",
            activebackground="#2E181C",
            activeforeground="#FF5555",
            bd=1,
            relief="solid",
            pady=8,
            command=self.test_penalty,
            cursor="hand2"
        )
        test_btn.pack(fill="x")

    def _on_cam_preview_toggle(self):
        self.preview_active = self.show_cam_preview.get()
        if not self.preview_active:
            self.cam_preview_label.configure(
                image="",
                text="\n\nCamera preview hidden (monitoring in background to save CPU)."
            )
            self._current_photo_image = None
        else:
            self.cam_preview_label.configure(
                image="",
                text="\n\nWebcam feed will appear here when Sentinel is started.\n(Live face & posture tracking)"
            )

    # -------------------------------------------------------------
    # Settings Tab (Scrollable)
    # -------------------------------------------------------------
    def _build_settings_tab(self):
        self.settings_scroll = ScrollableFrame(self.tab_settings, bg="#0D0E12")
        self.settings_scroll.pack(fill="both", expand=True)
        content = self.settings_scroll.scrollable_window

        s_card = tk.LabelFrame(content, text=" Configuration & Hardware Preferences ",
                               font=("Segoe UI", 10, "bold"),
                               bg="#15171E", fg="#EDEDF0", bd=1, relief="solid", padx=20, pady=18)
        s_card.pack(fill="both", expand=True, padx=10, pady=10)

        # 1. Target Jumping Jacks
        row1 = tk.Frame(s_card, bg="#15171E")
        row1.pack(fill="x", pady=8)
        tk.Label(row1, text="Penalty Jumping Jack Goal (Reps):", font=("Segoe UI", 10, "bold"),
                 bg="#15171E", fg="#EDEDF0").pack(side="left")
        self.target_spin = tk.Spinbox(row1, from_=1, to=100, width=6, font=("Segoe UI", 11),
                                      bg="#0D0E12", fg="#EDEDF0", bd=1)
        self.target_spin.delete(0, "end")
        self.target_spin.insert(0, str(self.settings.get("target_jumps", 10)))
        self.target_spin.pack(side="right")

        # 2. Speaker Output Selection (Laptop or FreeWili)
        row2 = tk.Frame(s_card, bg="#15171E")
        row2.pack(fill="x", pady=10)
        tk.Label(row2, text="Speaker Output Device:", font=("Segoe UI", 10, "bold"),
                 bg="#15171E", fg="#EDEDF0").pack(side="left")

        self.speaker_var = tk.StringVar(value=self.settings.get("speaker_output", "laptop"))
        spk_frame = tk.Frame(row2, bg="#15171E")
        spk_frame.pack(side="right")

        rb_laptop = tk.Radiobutton(
            spk_frame, text="Laptop Speakers (Loud & Clear)",
            variable=self.speaker_var, value="laptop",
            font=("Segoe UI", 10), bg="#15171E", fg="#EDEDF0",
            selectcolor="#0D0E12", activebackground="#15171E"
        )
        rb_laptop.pack(anchor="w")

        rb_freewili = tk.Radiobutton(
            spk_frame, text="FreeWili Onboard Speaker (Waist I2S)",
            variable=self.speaker_var, value="freewili",
            font=("Segoe UI", 10), bg="#15171E", fg="#A1A1AA",
            selectcolor="#0D0E12", activebackground="#15171E"
        )
        rb_freewili.pack(anchor="w")

        # 3. FreeWili Volume Slider
        row3 = tk.Frame(s_card, bg="#15171E")
        row3.pack(fill="x", pady=8)
        tk.Label(row3, text="FreeWili Speaker Volume (%):", font=("Segoe UI", 10, "bold"),
                 bg="#15171E", fg="#EDEDF0").pack(side="left")

        self.vol_label = tk.Label(row3, text=f"{self.settings.get('freewili_volume', 100)}%",
                                  font=("Segoe UI", 10, "bold"), bg="#15171E", fg="#EDEDF0")
        self.vol_label.pack(side="right", padx=(5, 0))

        self.vol_slider = ttk.Scale(row3, from_=0, to=100, orient="horizontal",
                                    command=self._on_volume_slider)
        self.vol_slider.set(self.settings.get("freewili_volume", 100))
        self.vol_slider.pack(side="right", fill="x", expand=True, padx=15)

        # 4. Connection Mode
        row4 = tk.Frame(s_card, bg="#15171E")
        row4.pack(fill="x", pady=8)
        tk.Label(row4, text="FreeWili Connection Mode:", font=("Segoe UI", 10, "bold"),
                 bg="#15171E", fg="#EDEDF0").pack(side="left")

        self.mode_var = tk.StringVar(value=self.settings.get("connection_mode", "ble"))
        mode_cb = ttk.Combobox(row4, textvariable=self.mode_var,
                               values=["ble", "serial", "mock"], state="readonly", width=12,
                               font=("Segoe UI", 10))
        mode_cb.pack(side="right")

        # 5. Serial Port
        self.row_port = tk.Frame(s_card, bg="#15171E")
        self.row_port.pack(fill="x", pady=8)
        tk.Label(self.row_port, text="USB Serial Port (if Serial mode):", font=("Segoe UI", 10),
                 bg="#15171E", fg="#A1A1AA").pack(side="left")
        self.port_entry = tk.Entry(self.row_port, font=("Segoe UI", 10), bg="#0D0E12", fg="#EDEDF0",
                                   width=10, bd=1)
        self.port_entry.insert(0, self.settings.get("serial_port", "COM3"))
        self.port_entry.pack(side="right")

        # 6. Webcam Index & Trigger Duration
        row6 = tk.Frame(s_card, bg="#15171E")
        row6.pack(fill="x", pady=8)
        tk.Label(row6, text="Webcam Device Index:", font=("Segoe UI", 10),
                 bg="#15171E", fg="#A1A1AA").pack(side="left")
        self.cam_spin = tk.Spinbox(row6, from_=0, to=10, width=5, font=("Segoe UI", 10),
                                   bg="#0D0E12", fg="#EDEDF0", bd=1)
        self.cam_spin.delete(0, "end")
        self.cam_spin.insert(0, str(self.settings.get("camera_index", 0)))
        self.cam_spin.pack(side="right")

        row7 = tk.Frame(s_card, bg="#15171E")
        row7.pack(fill="x", pady=8)
        tk.Label(row7, text="Phone Look-Down Trigger (sec):", font=("Segoe UI", 10),
                 bg="#15171E", fg="#A1A1AA").pack(side="left")
        self.trig_spin = tk.Spinbox(row7, from_=1.0, to=15.0, increment=0.5, width=5,
                                    font=("Segoe UI", 10), bg="#0D0E12", fg="#EDEDF0", bd=1)
        self.trig_spin.delete(0, "end")
        self.trig_spin.insert(0, str(self.settings.get("trigger_duration_sec", 3.5)))
        self.trig_spin.pack(side="right")

        # Save Button with Frosted Matte Linear Gradient
        save_btn = GradientButton(
            s_card,
            text="💾   SAVE & APPLY SETTINGS",
            command=self.save_and_apply_settings,
            width_px=420,
            height_px=42,
            color1="#1E222C",
            color2="#14161E",
            hover_color1="#2B303E",
            hover_color2="#1E222C",
            fg="#EDEDF0",
            corner_radius=6,
        )
        save_btn.pack(fill="x", pady=(20, 5))

    def _on_volume_slider(self, val):
        pct = int(float(val))
        self.vol_label.configure(text=f"{pct}%")

    # -------------------------------------------------------------
    # Settings Application & FreeWili Sync
    # -------------------------------------------------------------
    def save_and_apply_settings(self):
        try:
            target = int(self.target_spin.get())
            vol = int(self.vol_slider.get())
            mode = self.mode_var.get()
            port = self.port_entry.get().strip()
            cam = int(self.cam_spin.get())
            trig = float(self.trig_spin.get())
            spk = self.speaker_var.get()

            self.settings["target_jumps"] = target
            self.settings["freewili_volume"] = vol
            self.settings["connection_mode"] = mode
            self.settings["serial_port"] = port
            self.settings["camera_index"] = cam
            self.settings["trigger_duration_sec"] = trig
            self.settings["speaker_output"] = spk

            save_settings(self.settings)

            # Apply to audio manager
            self.audio.set_output_destination(spk)
            self.audio_dest_info.configure(text=f"Active Speaker: {spk.upper()} SPEAKER")

            # Apply to FreeWili client
            self.freewili.set_target(target)
            self.freewili.set_volume(vol)
            self.reps_display.configure(text=f"REPS: 0 / {target}")

            messagebox.showinfo("Focus Agent", "Settings saved and applied successfully!")
        except Exception as e:
            messagebox.showerror("Settings Error", f"Invalid input values: {e}")

    def update_freewili_connection(self, initial: bool = False):
        mode = self.settings.get("connection_mode", "ble")
        port = self.settings.get("serial_port", "COM3")
        target = self.settings.get("target_jumps", 10)
        vol = self.settings.get("freewili_volume", 100)

        if mode == "ble":
            self.conn_badge.configure(text="BLE: SCANNING...", bg="#201F18", fg="#EDEDF0")
            self.freewili.start_ble()
        elif mode == "serial":
            self.conn_badge.configure(text=f"SERIAL: {port}", bg="#181C26", fg="#EDEDF0")
            self.freewili.start_serial(port)
        else:
            self.conn_badge.configure(text="MOCK MODE", bg="#1C1E26", fg="#EDEDF0")
            self.freewili.start_mock()

        # Send initial config after slight delay
        self.root.after(1000, lambda: self.freewili.set_target(target))
        self.root.after(1200, lambda: self.freewili.set_volume(vol))

    # -------------------------------------------------------------
    # Telemetry Updates (Thread-safe)
    # -------------------------------------------------------------
    def on_freewili_telemetry(self, t: FreeWiliTelemetry):
        self.event_queue.put(("telemetry", t))

    def _process_telemetry_ui(self, t: FreeWiliTelemetry):
        # Update connection badge
        if self.freewili.is_connected:
            self.conn_badge.configure(text="CONNECTED", bg="#18221D", fg="#EDEDF0")
        else:
            self.conn_badge.configure(text="DISCONNECTED", bg="#261416", fg="#EF4444")

        # Update Live G and State
        g_val = getattr(t, "g_mg", 1000) / 1000.0
        peak_raw = getattr(t, "peak_mg", getattr(t, "peak_g_mg", 0))
        pk_val = peak_raw / 1000.0
        st_name = getattr(t, "state_name", "READY")
        self.accel_info.configure(
            text=f"Motion: [ {st_name} ] | G-Magnitude: {g_val:.2f}g | Peak: {pk_val:.2f}g"
        )

        target = self.settings.get("target_jumps", 10)

        # Update Penalty / Jump counting & Dynamic Progress Bar
        current_reps = self.jumps_in_penalty if self.penalty_active else t.jumps
        if self.penalty_active:
            self.jumps_in_penalty = max(0, t.jumps - self.penalty_start_jumps)
            current_reps = self.jumps_in_penalty
            self.reps_display.configure(text=f"REPS: {self.jumps_in_penalty} / {target}")

            # Forward to fullscreen overlay
            self.overlay.update_reps(
                current=self.jumps_in_penalty,
                target=target,
                state_name=st_name,
                g_mg=getattr(t, "g_mg", 1000)
            )

            # Check if target achieved
            if self.jumps_in_penalty >= target:
                self.penalty_active = False
                if self.detector:
                    self.detector.reset_penalty()
                logger.info("Jumping jack goal completed! Clearing penalty.")
                self.status_banner.configure(
                    text="PENALTY CLEARED // EXCELLENT DISCIPLINE!",
                    bg="#181A22",
                    fg="#EDEDF0"
                )
                self.audio.play(SOUND_PENALTY_CLEARED)
                self.overlay.show_victory_and_dismiss()
        else:
            self.reps_display.configure(text=f"REPS: {t.jumps} / {target}")

        # Update Live Dashboard Progress Canvas (Frosted Silver or Crimson)
        if hasattr(self, "dash_prog_canvas") and self.dash_prog_canvas.winfo_exists():
            c_w = self.dash_prog_canvas.winfo_width()
            if c_w < 10:
                c_w = 460
            ratio = min(1.0, current_reps / float(target)) if target > 0 else 0.0
            fill_w = int(c_w * ratio)
            bar_col = "#EF4444" if self.penalty_active else "#EDEDF0"
            self.dash_prog_canvas.coords(self._dash_fill_id, 0, 0, fill_w, 12)
            self.dash_prog_canvas.itemconfig(self._dash_fill_id, fill=bar_col)

    # -------------------------------------------------------------
    # Penalty Management
    # -------------------------------------------------------------
    def trigger_penalty(self):
        """Triggered upon webcam doomscroll detection."""
        if self.penalty_active:
            return

        self.penalty_active = True
        self.penalty_start_jumps = getattr(self.freewili.latest_telemetry, "jumps", 0)
        self.jumps_in_penalty = 0
        self.last_reprimand_time = time.time()

        target = self.settings.get("target_jumps", 10)
        logger.warning(f"DOOMSCROLL PENALTY TRIGGERED! Target: {target}")

        try:
            self.status_banner.configure(
                text=f"🚨 PENALTY ACTIVE // DO {target} JUMPING JACKS! 🚨",
                bg="#261215",
                fg="#EF4444"
            )
        except Exception as e:
            logger.error(f"Error configuring status banner: {e}")

        # 1. Sync target to FreeWili screen
        try:
            self.freewili.set_target(target)
        except Exception as e:
            logger.error(f"Error sending target to FreeWili: {e}")

        # 2. Show Fullscreen Blocking Overlay
        try:
            self.overlay.show(target_reps=target)
        except Exception as e:
            logger.error(f"Error displaying overlay: {e}", exc_info=True)

        # 3. Play vocal drill sergeant swivel neck reprimand
        try:
            self.audio.play(SOUND_SWIVEL_NECK)
        except Exception as e:
            logger.error(f"Error playing swivel neck audio: {e}", exc_info=True)

    def test_penalty(self):
        """Test button for user to verify the overlay and audio immediately."""
        self.trigger_penalty()

    def reset_penalty_state(self):
        """Called upon emergency bypass."""
        self.penalty_active = False
        if self.detector:
            self.detector.reset_penalty()
        target = self.settings.get("target_jumps", 10)
        self.status_banner.configure(
            text="SENTINEL MONITORING // FOCUS SECURE",
            bg="#181A22",
            fg="#EDEDF0"
        )
        self.reps_display.configure(text=f"REPS: 0 / {target}")

    def recalibrate_baseline(self):
        """Manually reset baseline posture to current position."""
        if self.detector:
            self.detector.calibrate_baseline()
            messagebox.showinfo("Focus Agent", "Posture baseline recalibrated to current position!")
        else:
            messagebox.showinfo("Focus Agent", "Start Sentinel before recalibrating baseline posture.")

    # -------------------------------------------------------------
    # Sentinel Monitoring Worker
    # -------------------------------------------------------------
    def toggle_sentinel(self):
        if self.is_monitoring:
            self.stop_sentinel()
        else:
            self.start_sentinel()

    def start_sentinel(self):
        if self.is_monitoring:
            return

        self.is_monitoring = True
        self.start_btn.update_gradient("#282D3A", "#1C202A", "#353B4D", "#282D3A", text="⏳   STARTING CAMERA...")
        self.status_banner.configure(
            text="INITIALIZING CAMERA & DEEP LEARNING DETECTOR...",
            bg="#181A22",
            fg="#EDEDF0"
        )

        self.monitor_thread = threading.Thread(target=self._monitor_worker, daemon=True)
        self.monitor_thread.start()

    def stop_sentinel(self):
        self.is_monitoring = False
        if self.detector:
            self.detector.reset_penalty()
        if self.cap:
            try:
                self.cap.release()
            except Exception:
                pass
            self.cap = None

        self.start_btn.update_gradient("#1E222C", "#14161E", "#2B303E", "#1E222C", text="▶   START SENTINEL")
        self.status_banner.configure(
            text="SENTINEL STOPPED // CLICK 'START' TO RESUME",
            bg="#181A22",
            fg="#A1A1AA"
        )
        if self.cam_preview_label:
            self.cam_preview_label.configure(
                image="",
                text="\n\nSentinel Stopped. Click 'Start Sentinel' to activate webcam."
            )
            self._current_photo_image = None

    def _monitor_worker(self):
        cam_idx = self.settings.get("camera_index", 0)
        logger.info(f"Opening camera index {cam_idx} in worker thread...")

        # Open camera safely in background thread (avoids Tkinter STA COM conflicts)
        cap = cv2.VideoCapture(cam_idx, cv2.CAP_DSHOW)
        if not cap or not cap.isOpened():
            logger.info("DirectShow open failed, trying default VideoCapture backend...")
            cap = cv2.VideoCapture(cam_idx)

        if not cap or not cap.isOpened():
            logger.error(f"Cannot open webcam device index {cam_idx}")
            self.event_queue.put(("camera_failed", f"Cannot open webcam device index {cam_idx}.\nCheck device connection or permissions."))
            return

        # Configure standard resolution and framerate
        try:
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            cap.set(cv2.CAP_PROP_FPS, 30)
        except Exception:
            pass

        self.cap = cap

        try:
            self.detector = DoomscrollDetector(
                trigger_duration_sec=self.settings.get("trigger_duration_sec", 3.5)
            )
            logger.info("DoomscrollDetector initialized successfully with YuNet/Haar.")
        except Exception as e:
            logger.error(f"Failed to initialize DoomscrollDetector: {e}", exc_info=True)
            self.event_queue.put(("camera_failed", f"Failed to initialize face detector: {e}"))
            return

        # Signal GUI thread that sentinel is actively running
        self.event_queue.put(("sentinel_ready", None))

        while self.is_monitoring and self.cap and self.cap.isOpened():
            try:
                ret, frame = self.cap.read()
                if not ret or frame is None:
                    time.sleep(0.04)
                    continue

                frame = cv2.flip(frame, 1)
                annotated_frame, is_doomscroll, dur_down = self.detector.process_frame(frame)

                # Trigger penalty if doomscrolling detected
                if is_doomscroll and not self.penalty_active:
                    logger.warning(f"Doomscroll detected in monitor loop! dur_down={dur_down:.1f}s. Enqueueing penalty.")
                    self.event_queue.put(("penalty", None))

                # Periodic motivational reprimand every 14s during penalty
                if self.penalty_active and (time.time() - self.last_reprimand_time > 14.0):
                    self.last_reprimand_time = time.time()
                    self.event_queue.put(("reprimand", None))

                # Render embedded camera preview inside the app if enabled
                if self.preview_active:
                    rgb = cv2.cvtColor(annotated_frame, cv2.COLOR_BGR2RGB)
                    h, w = rgb.shape[:2]
                    # Preserve exact camera aspect ratio within 480x360 container
                    scale = min(480.0 / w, 360.0 / h)
                    new_w = max(1, int(w * scale))
                    new_h = max(1, int(h * scale))
                    small_frame = cv2.resize(rgb, (new_w, new_h), interpolation=cv2.INTER_AREA)
                    pil_img = Image.fromarray(small_frame)
                    try:
                        self.preview_queue.get_nowait()
                    except queue.Empty:
                        pass
                    try:
                        self.preview_queue.put_nowait(pil_img)
                    except queue.Full:
                        pass

                time.sleep(0.03)
            except Exception as e:
                logger.error(f"Error in monitor loop iteration: {e}", exc_info=True)
                time.sleep(0.1)

        logger.info("Monitor worker loop exited.")

    def _poll_event_queue(self):
        try:
            while True:
                evt, data = self.event_queue.get_nowait()
                try:
                    if evt == "telemetry":
                        self._process_telemetry_ui(data)
                    elif evt == "penalty":
                        self.trigger_penalty()
                    elif evt == "reprimand":
                        self.audio.play_random_reprimand()
                    elif evt == "sentinel_ready":
                        self.start_btn.update_gradient("#C62828", "#8E0000", "#D32F2F", "#B71C1C", text="⏹   STOP SENTINEL")
                        self.status_banner.configure(
                            text="SENTINEL ACTIVE // MONITORING POSTURE & PHONE ACTIVITY",
                            bg="#221316",
                            fg="#EF4444"
                        )
                    elif evt == "camera_failed":
                        self.stop_sentinel()
                        messagebox.showerror("Camera Error", str(data))
                except Exception as ex:
                    logger.error(f"Error handling event '{evt}': {ex}", exc_info=True)
        except queue.Empty:
            pass
        except Exception as e:
            logger.error(f"Error in event poller: {e}", exc_info=True)
        finally:
            self.root.after(30, self._poll_event_queue)

    def _poll_preview_queue(self):
        pil_img = None
        try:
            while True:
                pil_img = self.preview_queue.get_nowait()
        except queue.Empty:
            pass

        if pil_img is not None and self.is_monitoring and self.preview_active:
            photo = ImageTk.PhotoImage(image=pil_img)
            self._current_photo_image = photo
            if self.cam_preview_label and self.cam_preview_label.winfo_exists():
                self.cam_preview_label.configure(image=photo, text="")
                self.cam_preview_label.image = photo

        self.root.after(33, self._poll_preview_queue)

    def minimize_to_background(self):
        """Minimize desktop window to run quietly in background."""
        self.root.iconify()

    def on_close(self):
        self.stop_sentinel()
        if self.freewili:
            self.freewili.stop()
        self.root.destroy()
        sys.exit(0)
