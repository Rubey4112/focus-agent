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
from ui_effects import GradientButton, create_horizontal_gradient_image, create_vertical_gradient_image, create_camera_standby_image


class ScrollableFrame(tk.Frame):
    """Frosted Charcoal Scrollable Container with custom styled dark scrollbar and mousewheel support."""

    def __init__(self, container, bg="#0D0E12", max_width=860, *args, **kwargs):
        super().__init__(container, bg=bg, *args, **kwargs)
        self.max_width = max_width
        self.canvas = tk.Canvas(self, bg=bg, bd=0, highlightthickness=0)
        
        # Configure sleek dark scrollbar
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(
            "Dark.Vertical.TScrollbar",
            gripcount=0,
            background="#252834",
            darkcolor="#15171E",
            lightcolor="#15171E",
            troughcolor="#0D0E12",
            bordercolor="#0D0E12",
            arrowcolor="#8E94A5"
        )
        style.map(
            "Dark.Vertical.TScrollbar",
            background=[("active", "#3A3F52"), ("pressed", "#1E202A")]
        )

        self.scrollbar = ttk.Scrollbar(self, orient="vertical", style="Dark.Vertical.TScrollbar", command=self.canvas.yview)
        self.scrollable_window = tk.Frame(self.canvas, bg=bg)

        self.scrollable_window.bind(
            "<Configure>",
            self._on_content_configure
        )

        self._window_id = self.canvas.create_window((0, 0), window=self.scrollable_window, anchor="nw")

        self.canvas.pack(side="left", fill="both", expand=True)
        # Scrollbar will be dynamically managed when content exceeds canvas height
        self._scrollbar_visible = False

        self.bind_all("<MouseWheel>", self._on_mousewheel)
        self.canvas.bind("<Configure>", self._on_canvas_configure)

    def _on_content_configure(self, event=None):
        canvas_width = self.canvas.winfo_width()
        content_height = self.scrollable_window.winfo_reqheight()
        self.canvas.configure(scrollregion=(0, 0, max(canvas_width, 10), max(content_height, 10)))
        self._update_scrollbar_visibility()

    def _update_scrollbar_visibility(self):
        self.update_idletasks()
        content_height = self.scrollable_window.winfo_reqheight()
        canvas_height = self.canvas.winfo_height()
        if content_height > canvas_height and canvas_height > 10:
            if not self._scrollbar_visible:
                self.scrollbar.pack(side="right", fill="y")
                self._scrollbar_visible = True
        else:
            if self._scrollbar_visible:
                self.scrollbar.pack_forget()
                self._scrollbar_visible = False

    def _on_canvas_configure(self, event):
        canvas_width = event.width
        target_width = min(self.max_width, max(500, canvas_width - 32))
        x_offset = max(0, (canvas_width - target_width) // 2)
        self.canvas.coords(self._window_id, x_offset, 0)
        self.canvas.itemconfig(self._window_id, width=target_width)
        content_height = self.scrollable_window.winfo_reqheight()
        self.canvas.configure(scrollregion=(0, 0, canvas_width, max(content_height, 10)))
        self._update_scrollbar_visibility()

    def _on_mousewheel(self, event):
        if self.winfo_exists() and self.canvas.winfo_exists():
            bbox = self.canvas.bbox("all")
            if bbox and (bbox[3] - bbox[1] > self.canvas.winfo_height()):
                self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")


class FocusAgentApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Focus Agent - Discipline Sentinel")
        self.root.geometry("860x860")
        self.root.minsize(700, 750)
        self.root.configure(bg="#0D0E12")

        # Maximize application window by default on boot
        try:
            self.root.state("zoomed")
        except Exception:
            try:
                self.root.attributes("-zoomed", True)
            except Exception:
                screen_w = self.root.winfo_screenwidth()
                screen_h = self.root.winfo_screenheight()
                self.root.geometry(f"{screen_w}x{screen_h}+0+0")

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
        style.configure(
            "TNotebook.Tab",
            background="#14161F",
            foreground="#71717A",
            lightcolor="#222532",
            bordercolor="#222532",
            darkcolor="#14161F",
            padding=[20, 8],
            font=("Segoe UI", 9, "bold")
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", "#1C1F2A")],
            foreground=[("selected", "#EDEDF0")],
            bordercolor=[("selected", "#2E3244")]
        )

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
        # High-precision architectural header with 1px zinc bottom hairline
        hdr_frame = tk.Frame(self.root, height=54, bg="#0D0E12")
        hdr_frame.pack(fill="x", side="top")
        hdr_frame.pack_propagate(False)

        # Centered header content container matching content max-width
        self.hdr_content = tk.Frame(hdr_frame, bg="#0D0E12")
        self.hdr_content.place(relx=0.5, rely=0.5, anchor="center", width=860, height=54)

        # Wordmark + discipline badge in single structured flex container
        wordmark_box = tk.Frame(self.hdr_content, bg="#0D0E12")
        wordmark_box.pack(side="left", padx=0, pady=10)

        title_lbl = tk.Label(
            wordmark_box, text="FOCUS AGENT", font=("Segoe UI", 15, "bold"),
            fg="#EDEDF0", bg="#0D0E12"
        )
        title_lbl.pack(side="left")

        # Architectural hair divider
        tk.Label(
            wordmark_box, text="—", font=("Segoe UI", 12),
            fg="#3F4250", bg="#0D0E12", padx=12
        ).pack(side="left")

        sub_lbl = tk.Label(
            wordmark_box, text="DISCIPLINE SENTINEL", font=("Segoe UI", 9, "bold"),
            fg="#71717A", bg="#0D0E12"
        )
        sub_lbl.pack(side="left")

        # Hardware connection status pill on header right
        self.conn_badge = tk.Label(
            self.hdr_content, text="● BLE SCANNING", font=("Segoe UI", 9, "bold"),
            bg="#0F243A", fg="#38BDF8", padx=12, pady=4,
            bd=1, relief="solid", highlightthickness=1, highlightbackground="#1E3E66"
        )
        self.conn_badge.pack(side="right", padx=0, pady=12)

        # 1px border stroke below header
        hdr_stroke = tk.Frame(self.root, height=1, bg="#20222B")
        hdr_stroke.pack(fill="x", side="top")

        # Persistent Architectural Footer Strip (Anchors bottom viewport)
        self.footer_stroke = tk.Frame(self.root, height=1, bg="#1E202B")
        self.footer_stroke.pack(fill="x", side="bottom")

        self.footer_frame = tk.Frame(self.root, height=30, bg="#0A0B0E")
        self.footer_frame.pack(fill="x", side="bottom")
        self.footer_frame.pack_propagate(False)

        self.footer_content = tk.Frame(self.footer_frame, bg="#0A0B0E")
        self.footer_content.place(relx=0.5, rely=0.5, anchor="center", width=860, height=30)

        tk.Label(
            self.footer_content,
            text="CORE SENTINEL · OPENCV YUNET ENGINE READY",
            font=("Consolas", 8, "bold"),
            fg="#525866",
            bg="#0A0B0E"
        ).pack(side="left")

        tk.Label(
            self.footer_content,
            text="POSTURE TRACKER: ARMED · LOW LATENCY",
            font=("Consolas", 8, "bold"),
            fg="#525866",
            bg="#0A0B0E"
        ).pack(side="right")

        # Studio Pill Tab Switcher Row (Centered)
        nav_row = tk.Frame(self.root, height=44, bg="#0D0E12")
        nav_row.pack(fill="x", side="top")
        nav_row.pack_propagate(False)

        self.nav_content = tk.Frame(nav_row, bg="#0D0E12")
        self.nav_content.place(relx=0.5, rely=0.5, anchor="center", width=860, height=44)

        self._active_tab = "dash"
        self._pill_dash = tk.Button(
            self.nav_content,
            text="DASHBOARD",
            font=("Segoe UI", 9, "bold"),
            bg="#222634",
            fg="#EDEDF0",
            activebackground="#2B3042",
            activeforeground="#FFFFFF",
            bd=0,
            highlightthickness=0,
            padx=16,
            pady=6,
            cursor="hand2",
            command=lambda: self._switch_view("dash")
        )
        self._pill_dash.pack(side="left", padx=(0, 8))

        self._pill_settings = tk.Button(
            self.nav_content,
            text="SETTINGS",
            font=("Segoe UI", 9, "bold"),
            bg="#14161F",
            fg="#71717A",
            activebackground="#222634",
            activeforeground="#EDEDF0",
            bd=0,
            highlightthickness=0,
            padx=16,
            pady=6,
            cursor="hand2",
            command=lambda: self._switch_view("settings")
        )
        self._pill_settings.pack(side="left")

        # Main Content Containers
        self.container_frame = tk.Frame(self.root, bg="#0D0E12")
        self.container_frame.pack(expand=True, fill="both", padx=0, pady=0)

        self.tab_dash = tk.Frame(self.container_frame, bg="#0D0E12")
        self.tab_settings = tk.Frame(self.container_frame, bg="#0D0E12")

        self.tab_dash.pack(expand=True, fill="both")

        self._build_dashboard_tab()
        self._build_settings_tab()

        self.root.bind("<Configure>", self._on_window_resize)

    def _on_window_resize(self, event):
        if event.widget == self.root:
            w = event.width
            target_w = min(860, max(500, w - 32))
            if hasattr(self, "hdr_content") and self.hdr_content.winfo_exists():
                self.hdr_content.place_configure(width=target_w)
            if hasattr(self, "nav_content") and self.nav_content.winfo_exists():
                self.nav_content.place_configure(width=target_w)
            if hasattr(self, "footer_content") and self.footer_content.winfo_exists():
                self.footer_content.place_configure(width=target_w)

    def _switch_view(self, view_name: str):
        if view_name == "dash":
            self.tab_settings.pack_forget()
            self.tab_dash.pack(expand=True, fill="both")
            self._pill_dash.configure(bg="#222634", fg="#EDEDF0")
            self._pill_settings.configure(bg="#14161F", fg="#71717A")
            self._active_tab = "dash"
        else:
            self.tab_dash.pack_forget()
            self.tab_settings.pack(expand=True, fill="both")
            self._pill_dash.configure(bg="#14161F", fg="#71717A")
            self._pill_settings.configure(bg="#222634", fg="#EDEDF0")
            self._active_tab = "settings"

    # -------------------------------------------------------------
    # Dashboard Tab (Scrollable)
    # -------------------------------------------------------------
    def _build_dashboard_tab(self):
        self.dash_scroll = ScrollableFrame(self.tab_dash, bg="#0D0E12", max_width=860)
        self.dash_scroll.pack(fill="both", expand=True)
        content = self.dash_scroll.scrollable_window

        # Section 1: Sentinel Status & Action Panel (Flat dark surface, 1px perimeter border)
        ctrl_card = tk.Frame(content, bg="#13151C", bd=1, relief="solid", highlightthickness=1, highlightbackground="#222530")
        ctrl_card.pack(fill="x", padx=0, pady=(6, 6))

        # Status HUD Strip
        self.status_banner = tk.Label(
            ctrl_card,
            text="SENTINEL STANDBY · POSTURE ENGINE ARMED",
            font=("Segoe UI", 8, "bold"),
            bg="#181A24",
            fg="#A1A1AA",
            pady=8,
            padx=16,
            anchor="w"
        )
        self.status_banner.pack(fill="x")

        # Control Row inside Action Panel
        action_row = tk.Frame(ctrl_card, bg="#13151C", padx=16, pady=10)
        action_row.pack(fill="x")

        # High-Precision Tactical Primary CTA (Elevated Azure Glow Hero Button)
        self.start_btn = GradientButton(
            action_row,
            text="▶   START SENTINEL",
            command=self.toggle_sentinel,
            width_px=210,
            height_px=38,
            color1="#1B385D",
            color2="#102542",
            hover_color1="#265185",
            hover_color2="#18365E",
            fg="#F0F9FF",
            bg="#13151C",
            corner_radius=4
        )
        self.start_btn.pack(side="left", padx=(0, 10))

        min_btn = tk.Button(
            action_row,
            text="MINIMIZE TO TRAY",
            font=("Segoe UI", 9, "bold"),
            bg="#161822",
            fg="#A1A1AA",
            activebackground="#222534",
            activeforeground="#FFFFFF",
            bd=1,
            relief="solid",
            highlightthickness=1,
            highlightbackground="#2A2D3A",
            padx=14,
            pady=7,
            command=self.minimize_to_background,
            cursor="hand2"
        )
        min_btn.pack(side="left")

        self.detector_chip = tk.Label(
            action_row,
            text="POSTURE ENGINE: YUNET + PRESAGE FOCUS",
            font=("Consolas", 8, "bold"),
            bg="#181A24",
            fg="#71717A",
            padx=12,
            pady=7,
            bd=1,
            relief="solid",
            highlightthickness=1,
            highlightbackground="#2A2D3A"
        )
        self.detector_chip.pack(side="right")

        # Section 2: Camera Feed Container
        self.cam_card = tk.Frame(content, bg="#13151C", bd=1, relief="solid", highlightthickness=1, highlightbackground="#222530")
        self.cam_card.pack(fill="x", padx=0, pady=(0, 6))

        cam_header = tk.Frame(self.cam_card, bg="#13151C", padx=16, pady=7)
        cam_header.pack(fill="x")

        tk.Label(
            cam_header, text="OPTICAL TELEMETRY", font=("Segoe UI", 8, "bold"),
            bg="#13151C", fg="#A1A1AA"
        ).pack(side="left")

        # HUD Preview checkbutton relocated to Viewport Card Header
        cam_chk = tk.Checkbutton(
            cam_header,
            text="LIVE VIEWPORT",
            variable=self.show_cam_preview,
            command=self._on_cam_preview_toggle,
            font=("Segoe UI", 8, "bold"),
            bg="#13151C",
            fg="#A1A1AA",
            selectcolor="#0D0E12",
            activebackground="#13151C",
            activeforeground="#EDEDF0",
            bd=0,
            highlightthickness=0
        )
        cam_chk.pack(side="right", padx=(10, 0))

        calib_btn = tk.Button(
            cam_header,
            text="RECALIBRATE BASELINE",
            font=("Segoe UI", 8, "bold"),
            bg="#161822",
            fg="#A1A1AA",
            activebackground="#242838",
            activeforeground="#FFFFFF",
            bd=1,
            relief="solid",
            highlightthickness=1,
            highlightbackground="#2A2D3A",
            padx=10,
            pady=3,
            command=self.recalibrate_baseline,
            cursor="hand2"
        )
        calib_btn.pack(side="right")

        cam_w = 640
        cam_h = 240
        self.cam_container = tk.Frame(self.cam_card, bg="#0D0E12", width=cam_w, height=cam_h)
        self.cam_container.pack(pady=(0, 8), padx=16)
        self.cam_container.pack_propagate(False)

        # Pre-render high-tech radar reticle standby graphic
        self._cam_standby_photo = ImageTk.PhotoImage(create_camera_standby_image(cam_w, cam_h))
        self.cam_preview_label = tk.Label(
            self.cam_container,
            image=self._cam_standby_photo,
            bg="#0D0E12",
            bd=0,
            highlightthickness=0
        )
        self.cam_preview_label.image = self._cam_standby_photo
        self.cam_preview_label.pack(expand=True, fill="both")

        # Section 3: Telemetry & Discipline Console
        telem_card = tk.Frame(content, bg="#13151C", bd=1, relief="solid", highlightthickness=1, highlightbackground="#222530", padx=16, pady=10)
        telem_card.pack(fill="x", padx=0, pady=(0, 8))

        # Telemetry Header Row
        t_hdr = tk.Frame(telem_card, bg="#13151C")
        t_hdr.pack(fill="x", pady=(0, 5))

        tk.Label(
            t_hdr, text="KINETIC ENFORCEMENT", font=("Segoe UI", 8, "bold"),
            bg="#13151C", fg="#A1A1AA"
        ).pack(side="left")

        # Compact discrete ghost test button inside header
        test_btn = tk.Button(
            t_hdr,
            text="TEST LOCKOUT",
            font=("Segoe UI", 7, "bold"),
            bg="#181A22",
            fg="#94A3B8",
            activebackground="#242836",
            activeforeground="#EF4444",
            bd=1,
            relief="solid",
            highlightthickness=1,
            highlightbackground="#2E3242",
            padx=10,
            pady=3,
            command=self.test_penalty,
            cursor="hand2"
        )
        test_btn.pack(side="right", padx=(10, 0))

        # Styled Audio Destination Metadata Badge
        self.audio_dest_info = tk.Label(
            t_hdr,
            text=f"AUDIO: {self.settings.get('speaker_output', 'laptop').upper()}",
            font=("Consolas", 8, "bold"),
            fg="#94A3B8",
            bg="#181A24",
            padx=10,
            pady=3,
            bd=1,
            relief="solid",
            highlightthickness=1,
            highlightbackground="#2A2D3A"
        )
        self.audio_dest_info.pack(side="right")

        # Large Architectural Rep Counter in Monospace Tabular
        self.reps_display = tk.Label(
            telem_card,
            text=f"00 / {self.settings.get('target_jumps', 10):02d}",
            font=("Consolas", 32, "bold"),
            fg="#EDEDF0",
            bg="#13151C"
        )
        self.reps_display.pack(anchor="center", pady=(1, 1))

        tk.Label(
            telem_card, text="COMPLETED REPETITIONS", font=("Segoe UI", 8, "bold"),
            bg="#13151C", fg="#8E94A5"
        ).pack(anchor="center", pady=(0, 6))

        # 10-Segment Tactile Gauge Canvas with Crisp Track Pips
        self.dash_prog_canvas = tk.Canvas(
            telem_card,
            height=14,
            bg="#13151C",
            bd=0,
            highlightthickness=0,
        )
        self.dash_prog_canvas.pack(fill="x", padx=16, pady=(0, 8))
        self._gauge_rects = []
        for b in range(10):
            rect = self.dash_prog_canvas.create_rectangle(
                0, 0, 0, 0,
                fill="#1E2230", outline="#31374A", width=1
            )
            self._gauge_rects.append(rect)

        self.dash_prog_canvas.bind("<Configure>", self._on_gauge_configure)

        # Structured 3-Column Telemetry Grid with Sleek Dark Metric Tiles
        telem_grid = tk.Frame(telem_card, bg="#13151C")
        telem_grid.pack(fill="x", pady=(0, 4), padx=10)

        # Tile 1: Status
        tile1 = tk.Frame(telem_grid, bg="#171922", bd=1, relief="solid", highlightthickness=1, highlightbackground="#252834", padx=12, pady=8)
        tile1.pack(side="left", expand=True, fill="x", padx=(0, 6))
        tk.Label(tile1, text="STATE", font=("Segoe UI", 7, "bold"), bg="#171922", fg="#71717A").pack()
        self.lbl_telem_state = tk.Label(tile1, text="STANDBY", font=("Consolas", 11, "bold"), bg="#171922", fg="#A1A1AA")
        self.lbl_telem_state.pack(pady=(2, 0))

        # Tile 2: Current G
        tile2 = tk.Frame(telem_grid, bg="#171922", bd=1, relief="solid", highlightthickness=1, highlightbackground="#252834", padx=12, pady=8)
        tile2.pack(side="left", expand=True, fill="x", padx=3)
        tk.Label(tile2, text="CURRENT G", font=("Segoe UI", 7, "bold"), bg="#171922", fg="#71717A").pack()
        self.lbl_telem_cur_g = tk.Label(tile2, text="1.00g", font=("Consolas", 11, "bold"), bg="#171922", fg="#EDEDF0")
        self.lbl_telem_cur_g.pack(pady=(2, 0))

        # Tile 3: Peak G
        tile3 = tk.Frame(telem_grid, bg="#171922", bd=1, relief="solid", highlightthickness=1, highlightbackground="#252834", padx=12, pady=8)
        tile3.pack(side="left", expand=True, fill="x", padx=(6, 0))
        tk.Label(tile3, text="PEAK G", font=("Segoe UI", 7, "bold"), bg="#171922", fg="#71717A").pack()
        self.lbl_telem_peak_g = tk.Label(tile3, text="0.00g", font=("Consolas", 11, "bold"), bg="#171922", fg="#EDEDF0")
        self.lbl_telem_peak_g.pack(pady=(2, 0))

    def _on_gauge_configure(self, event):
        w = event.width
        if w <= 20:
            return
        gap = 6
        avail_w = w - 10
        block_w = max(10, (avail_w - (9 * gap)) // 10)
        total_w = 10 * block_w + 9 * gap
        start_x = max(0, (w - total_w) // 2)
        for idx, rect in enumerate(self._gauge_rects):
            bx = start_x + idx * (block_w + gap)
            self.dash_prog_canvas.coords(rect, bx, 1, bx + block_w, 13)

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
        self.settings_scroll = ScrollableFrame(self.tab_settings, bg="#0D0E12", max_width=860)
        self.settings_scroll.pack(fill="both", expand=True)
        content = self.settings_scroll.scrollable_window

        s_card = tk.LabelFrame(content, text=" Configuration & Hardware Preferences ",
                               font=("Segoe UI", 10, "bold"),
                               bg="#15171E", fg="#EDEDF0", bd=1, relief="solid", padx=24, pady=18)
        s_card.pack(fill="x", expand=True, padx=0, pady=10)

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

        # 7. Presage SmartSpectra Settings Card
        p_card = tk.LabelFrame(
            content,
            text=" Presage SmartSpectra Focus & Distraction Sentinel ",
            font=("Segoe UI", 10, "bold"),
            bg="#15171E",
            fg="#EDEDF0",
            bd=1,
            relief="solid",
            highlightthickness=1,
            highlightbackground="#222530",
            padx=16,
            pady=12,
        )
        p_card.pack(fill="x", pady=(16, 16))

        p_row1 = tk.Frame(p_card, bg="#15171E")
        p_row1.pack(fill="x", pady=4)
        self.presage_enabled_var = tk.BooleanVar(value=self.settings.get("presage_enabled", True))
        tk.Checkbutton(
            p_row1,
            text="Enable Presage Attention & Gaze Sentinel (Detects Head Turn & Loss of Focus)",
            variable=self.presage_enabled_var,
            font=("Segoe UI", 9, "bold"),
            bg="#15171E",
            fg="#EDEDF0",
            selectcolor="#0D0E12",
            activebackground="#15171E",
            activeforeground="#EDEDF0",
        ).pack(side="left")

        p_row2 = tk.Frame(p_card, bg="#15171E")
        p_row2.pack(fill="x", pady=6)
        tk.Label(
            p_row2,
            text="Presage API Key:",
            font=("Segoe UI", 10),
            bg="#15171E",
            fg="#A1A1AA",
        ).pack(side="left")

        self.presage_key_entry = tk.Entry(
            p_row2,
            font=("Consolas", 10),
            bg="#0D0E12",
            fg="#EDEDF0",
            width=36,
            bd=1,
            show="*",
        )
        self.presage_key_entry.insert(
            0, self.settings.get("presage_api_key", "")
        )
        self.presage_key_entry.pack(side="right")

        p_row3 = tk.Frame(p_card, bg="#15171E")
        p_row3.pack(fill="x", pady=4)

        self._key_shown = False
        def _toggle_key_vis():
            self._key_shown = not self._key_shown
            self.presage_key_entry.configure(show="" if self._key_shown else "*")
            btn_show_key.configure(text="Hide Key" if self._key_shown else "Show Key")

        btn_show_key = tk.Button(
            p_row3,
            text="Show Key",
            font=("Segoe UI", 8),
            bg="#1E222C",
            fg="#A1A1AA",
            bd=1,
            relief="solid",
            command=_toggle_key_vis,
            cursor="hand2",
        )
        btn_show_key.pack(side="left", padx=(0, 10))

        btn_test_presage = tk.Button(
            p_row3,
            text="⚡ Verify Presage Cloud Auth",
            font=("Segoe UI", 8, "bold"),
            bg="#1B385D",
            fg="#60A5FA",
            bd=1,
            relief="solid",
            command=self._test_presage_connection,
            cursor="hand2",
        )
        btn_test_presage.pack(side="left")

        # Save Button with Frosted Matte Linear Gradient
        save_btn = GradientButton(
            content,
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
        save_btn.pack(fill="x", pady=(10, 15))

    def _on_volume_slider(self, val):
        pct = int(float(val))
        self.vol_label.configure(text=f"{pct}%")

    def _test_presage_connection(self):
        key = self.presage_key_entry.get().strip()
        if not key:
            messagebox.showerror("Presage Test", "Please enter a Presage API key.")
            return
        try:
            from presage_sentinel import PresageSentinel
            sentinel = PresageSentinel(api_key=key, enabled=True)
            ok = sentinel.start_session()
            if ok:
                sentinel.stop_session()
                messagebox.showinfo(
                    "Presage Test",
                    "Presage SmartSpectra Authentication Succeeded!\n\nAPI Key is valid and SDK graph initialized cleanly.",
                )
            else:
                err_detail = getattr(sentinel, "last_error_message", None) or "Please check your API key and internet connectivity."
                messagebox.showerror(
                    "Presage Test",
                    f"Presage Authentication Failed.\n\n{err_detail}",
                )
        except Exception as e:
            messagebox.showerror("Presage Test", f"Error connecting to Presage: {e}")

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

            presage_en = self.presage_enabled_var.get()
            presage_k = self.presage_key_entry.get().strip()

            self.settings["target_jumps"] = target
            self.settings["freewili_volume"] = vol
            self.settings["connection_mode"] = mode
            self.settings["serial_port"] = port
            self.settings["camera_index"] = cam
            self.settings["trigger_duration_sec"] = trig
            self.settings["speaker_output"] = spk
            self.settings["presage_enabled"] = presage_en
            self.settings["presage_api_key"] = presage_k

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
            self.conn_badge.configure(text="● BLE SCANNING", bg="#181A22", fg="#8E94A5")
            self.freewili.start_ble()
        elif mode == "serial":
            self.conn_badge.configure(text=f"● SERIAL {port}", bg="#181A22", fg="#8E94A5")
            self.freewili.start_serial(port)
        else:
            self.conn_badge.configure(text="● MOCK EMULATOR", bg="#181A22", fg="#8E94A5")
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
        # Extract telemetry parameters safely
        st_name = getattr(t, "state_name", "IDLE")
        g_val = getattr(t, "g_mg", 1000) / 1000.0
        pk_val = getattr(t, "peak_mg", getattr(t, "peak_g_mg", 0)) / 1000.0

        # Update connection badge
        if self.freewili.is_connected:
            self.conn_badge.configure(text="● HARDWARE LINKED", bg="#14231A", fg="#34D399")
        else:
            self.conn_badge.configure(text="● DISCONNECTED", bg="#261215", fg="#EF4444")

        # Update 3-Column Micro-Grid
        if hasattr(self, "lbl_telem_state"):
            self.lbl_telem_state.configure(text=st_name.upper())
        if hasattr(self, "lbl_telem_cur_g"):
            self.lbl_telem_cur_g.configure(text=f"{g_val:.2f}g")
        if hasattr(self, "lbl_telem_peak_g"):
            self.lbl_telem_peak_g.configure(text=f"{pk_val:.2f}g")

        target = self.settings.get("target_jumps", 10)

        # Update Penalty / Jump counting & Dynamic Progress Bar
        if self.penalty_active:
            if t.jumps < self.penalty_start_jumps:
                # Hardware device reset count to 0 upon receiving set_target
                self.penalty_start_jumps = 0
            self.jumps_in_penalty = max(0, t.jumps - self.penalty_start_jumps)
            current_reps = self.jumps_in_penalty
            self.reps_display.configure(text=f"{self.jumps_in_penalty:02d} / {target:02d}")

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
                    text="PENALTY RESOLVED  ·  DISCIPLINE RESTORED",
                    bg="#14231A",
                    fg="#34D399"
                )
                self.audio.play(SOUND_PENALTY_CLEARED)
                self.overlay.show_victory_and_dismiss()
        else:
            current_reps = t.jumps
            self.reps_display.configure(text=f"{t.jumps:02d} / {target:02d}")

        # Update Live Dashboard 10-Block Tactile Gauge (matching hardware)
        if hasattr(self, "_gauge_rects") and self._gauge_rects:
            ratio = min(1.0, current_reps / float(target)) if target > 0 else 0.0
            completed_blocks = int(round(ratio * 10))
            active_col = "#EF4444" if self.penalty_active else "#38BDF8"
            for idx, r_id in enumerate(self._gauge_rects):
                if idx < completed_blocks:
                    self.dash_prog_canvas.itemconfig(r_id, fill=active_col, outline=active_col)
                else:
                    self.dash_prog_canvas.itemconfig(r_id, fill="#1E2230", outline="#31374A")

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
            self.detector.release()
            self.detector = None
        if self.cap:
            try:
                self.cap.release()
            except Exception:
                pass
            self.cap = None

        self.start_btn.update_gradient("#1B385D", "#102542", "#265185", "#18365E", text="▶   START SENTINEL")
        self.status_banner.configure(
            text="SENTINEL STANDBY  ·  ACTIVATE POSTURE MONITORING",
            bg="#181A24",
            fg="#8E94A5"
        )
        if self.cam_preview_label:
            if hasattr(self, "_cam_standby_photo") and self._cam_standby_photo:
                self.cam_preview_label.configure(image=self._cam_standby_photo, text="")
                self.cam_preview_label.image = self._cam_standby_photo
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
                trigger_duration_sec=self.settings.get("trigger_duration_sec", 3.5),
                presage_api_key=self.settings.get("presage_api_key", None),
                presage_enabled=self.settings.get("presage_enabled", True),
            )
            logger.info("DoomscrollDetector initialized successfully with YuNet/Haar & Presage.")
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
                    # Preserve exact camera aspect ratio within 640x240 container
                    scale = min(640.0 / w, 240.0 / h)
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
