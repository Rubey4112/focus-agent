"""Fullscreen Blocking Penalty Overlay for Focus Agent.

Locks the screen, blocks all user interactions, and berates the user
with drill sergeant quotes until the required jumping jacks are verified.
"""

import tkinter as tk
from tkinter import ttk
import time
import logging

logger = logging.getLogger("PenaltyOverlay")


class PenaltyOverlay:
    def __init__(self, root: tk.Tk, on_emergency_unlock=None):
        self.root = root
        self.on_emergency_unlock = on_emergency_unlock
        self.window = None
        self.is_active = False

        self.target_reps = 10
        self.current_reps = 0
        self.current_state_name = "READY"
        self.current_g_mg = 1000

        # UI elements
        self.banner_label = None
        self.rep_count_label = None
        self.rep_rem_label = None
        self.progress_bar = None
        self.quote_label = None
        self.status_label = None
        self.card_frame = None

        self._flash_state = False
        self._flash_job = None

    def show(self, target_reps: int, initial_quote: str = None):
        """Display the blocking fullscreen overlay."""
        if self.is_active and self.window and self.window.winfo_exists():
            self.update_target(target_reps)
            return

        self.target_reps = target_reps
        self.current_reps = 0
        self.is_active = True

        try:
            # If main application was minimized to background, restore it so Toplevel can take over
            try:
                if self.root and self.root.winfo_exists() and self.root.state() == "iconic":
                    self.root.deiconify()
            except Exception:
                pass

            self.window = tk.Toplevel(self.root)
            self.window.title("FOCUS AGENT: SCREEN LOCKED")

            # Configure Fullscreen & Topmost
            self.window.attributes("-fullscreen", True)
            self.window.attributes("-topmost", True)
            self.window.configure(bg="#0c0d14")

            # Intercept close window events
            self.window.protocol("WM_DELETE_WINDOW", lambda: None)

            self._build_ui(initial_quote)

            # Force focus and grab all input
            self.window.deiconify()
            self.window.lift()
            self.window.focus_force()
            try:
                self.window.grab_set()
            except Exception as ge:
                logger.warning(f"Overlay grab_set: {ge}")

            self._start_alarm_pulse()
            logger.info("Fullscreen blocking penalty overlay activated.")
        except Exception as e:
            logger.error(f"Failed to display fullscreen overlay: {e}", exc_info=True)

    def _build_ui(self, initial_quote: str = None):
        # Perimeter Alarm Glow Borders (Top, Bottom, Left, Right)
        self.top_border = tk.Canvas(self.window, height=3, bg="#EF4444", bd=0, highlightthickness=0)
        self.top_border.pack(fill="x", side="top")
        self.bot_border = tk.Canvas(self.window, height=3, bg="#EF4444", bd=0, highlightthickness=0)
        self.bot_border.pack(fill="x", side="bottom")

        # Master Container
        container = tk.Frame(self.window, bg="#0C0D11")
        container.pack(expand=True, fill="both", padx=50, pady=30)

        # Header Warning Banner
        self.header_canvas = tk.Canvas(container, height=60, bg="#161820", bd=0, highlightthickness=0)
        self.header_canvas.pack(fill="x", pady=(10, 15))

        self.banner_label = tk.Label(
            self.header_canvas,
            text="🚨  SECURITY PROTOCOL: LOCKDOWN ACTIVE  🚨",
            font=("Segoe UI", 24, "bold"),
            fg="#EDEDF0",
            bg="#161820",
        )
        self.banner_label.pack(expand=True, pady=10)

        # Subtitle
        sub_title = tk.Label(
            container,
            text="UNAUTHORIZED OCULAR RECONNAISSANCE DETECTED // COMMENCE PHYSICAL PENALTY",
            font=("Segoe UI", 12, "bold"),
            fg="#EF4444",
            bg="#0C0D11",
        )
        sub_title.pack(pady=(0, 20))

        # Center Frosted Glass HUD Card
        self.card_frame = tk.Frame(container, bg="#161820", bd=1, relief="solid", padx=30, pady=24)
        self.card_frame.pack(expand=True, fill="both", padx=100, pady=5)

        # Accent Rim Line across top of card
        self.card_rim = tk.Canvas(self.card_frame, height=2, bg="#EF4444", bd=0, highlightthickness=0)
        self.card_rim.pack(fill="x", pady=(0, 15))

        goal_hdr = tk.Label(
            self.card_frame,
            text="PHYSICAL DISCIPLINE VERIFICATION",
            font=("Segoe UI", 12, "bold"),
            fg="#D1D5DB",
            bg="#161820",
        )
        goal_hdr.pack(pady=(0, 6))

        # Big Rep Counter in Centerpiece
        self.rep_count_label = tk.Label(
            self.card_frame,
            text=f"0 / {self.target_reps}",
            font=("Segoe UI", 72, "bold"),
            fg="#EF4444",
            bg="#161820",
        )
        self.rep_count_label.pack(pady=0)

        self.rep_rem_label = tk.Label(
            self.card_frame,
            text=f"EXECUTE {self.target_reps} JUMPING JACKS TO RESTORE SYSTEM ACCESS",
            font=("Segoe UI", 13, "bold"),
            fg="#EDEDF0",
            bg="#161820",
        )
        self.rep_rem_label.pack(pady=(4, 18))

        # Canvas Progress Bar (600x18)
        self.prog_canvas = tk.Canvas(
            self.card_frame,
            height=18,
            bg="#111218",
            bd=0,
            highlightthickness=1,
            highlightbackground="#2A2D38",
        )
        self.prog_canvas.pack(fill="x", padx=80, pady=(0, 18))
        self._prog_fill_id = self.prog_canvas.create_rectangle(0, 0, 0, 18, fill="#EF4444", outline="")

        # Live FreeWili Telemetry Badge
        self.status_label = tk.Label(
            self.card_frame,
            text="FreeWili Accelerometer: WAITING FOR JUMPS... (G: 1.00g)",
            font=("Consolas", 11),
            fg="#9CA3AF",
            bg="#161820",
        )
        self.status_label.pack(pady=(0, 10))

        # Drill Sergeant Reprimand Quote Card
        quote_text = initial_quote or (
            '"Put that phone down right now! You are pushing this planet away from you, '
            'and I am NOT impressed by the velocity! Move those legs!"'
        )
        quote_card = tk.Frame(container, bg="#161820", bd=1, relief="solid", padx=20, pady=12)
        quote_card.pack(fill="x", padx=100, pady=(15, 15))

        self.quote_label = tk.Label(
            quote_card,
            text=quote_text,
            font=("Segoe UI", 12, "italic"),
            fg="#EDEDF0",
            bg="#161820",
            wraplength=850,
            justify="center",
        )
        self.quote_label.pack()

        # Bottom Bar & Emergency Override
        bottom_bar = tk.Frame(container, bg="#0C0D11")
        bottom_bar.pack(fill="x", side="bottom")

        instr = tk.Label(
            bottom_bar,
            text="Wrist / waist sensor actively validating ground impact forces. Screen locked until rep count reached.",
            font=("Segoe UI", 10),
            fg="#71717A",
            bg="#0C0D11",
        )
        instr.pack(side="left")

        bypass_btn = tk.Button(
            bottom_bar,
            text="Emergency Override",
            font=("Segoe UI", 9, "bold"),
            bg="#1C1E26",
            fg="#9CA3AF",
            activebackground="#2A2D38",
            activeforeground="#EDEDF0",
            bd=1,
            relief="solid",
            padx=12,
            pady=4,
            command=self._emergency_clicked,
            cursor="hand2",
        )
        bypass_btn.pack(side="right")

    def _emergency_clicked(self):
        logger.warning("Emergency override activated by user.")
        if self.on_emergency_unlock:
            self.on_emergency_unlock()
        self.dismiss(victory=False)

    def _start_alarm_pulse(self):
        """Pulse the perimeter alarm glow and header banner."""
        if not self.is_active or not self.window:
            return

        self._flash_state = not self._flash_state
        border_col = "#EF4444" if self._flash_state else "#7F1D1D"
        hdr_bg = "#221316" if self._flash_state else "#161820"

        if hasattr(self, "top_border") and self.top_border.winfo_exists():
            self.top_border.configure(bg=border_col)
        if hasattr(self, "bot_border") and self.bot_border.winfo_exists():
            self.bot_border.configure(bg=border_col)
        if hasattr(self, "header_canvas") and self.header_canvas.winfo_exists():
            self.header_canvas.configure(bg=hdr_bg)
        if self.banner_label and self.banner_label.winfo_exists():
            self.banner_label.configure(bg=hdr_bg)

        # Enforce topmost aggressively
        if self.window and self.window.winfo_exists():
            self.window.lift()

        self._flash_job = self.window.after(650, self._start_alarm_pulse)

    def update_reps(self, current: int, target: int, state_name: str = "", g_mg: int = 1000):
        """Update live jump counter from FreeWili telemetry."""
        if not self.is_active or not self.window:
            return

        self.current_reps = current
        self.target_reps = target
        self.current_state_name = state_name
        self.current_g_mg = g_mg

        if self.rep_count_label and self.rep_count_label.winfo_exists():
            self.rep_count_label.configure(text=f"{current} / {target}")

        if self.rep_rem_label and self.rep_rem_label.winfo_exists():
            rem = max(0, target - current)
            self.rep_rem_label.configure(text=f"EXECUTE {rem} MORE JUMPING JACKS TO RESTORE SYSTEM ACCESS")

        if hasattr(self, "prog_canvas") and self.prog_canvas.winfo_exists():
            c_w = self.prog_canvas.winfo_width()
            if c_w < 10:
                c_w = 600
            ratio = min(1.0, current / float(target)) if target > 0 else 0.0
            fill_w = int(c_w * ratio)
            self.prog_canvas.coords(self._prog_fill_id, 0, 0, fill_w, 18)
            self.prog_canvas.itemconfig(self._prog_fill_id, fill="#EF4444")

        if self.status_label and self.status_label.winfo_exists():
            g_str = f"{g_mg / 1000.0:.2f}g"
            st_text = f"[{state_name}]" if state_name else ""
            self.status_label.configure(
                text=f"FreeWili Accelerometer: {st_text} | G-Force: {g_str} | Verified Reps: {current}/{target}"
            )

    def update_quote(self, quote: str):
        """Update displayed drill sergeant speech quote."""
        if self.quote_label and self.quote_label.winfo_exists():
            self.quote_label.configure(text=quote)

    def update_target(self, target_reps: int):
        self.target_reps = target_reps
        self.update_reps(self.current_reps, target_reps)

    def show_victory_and_dismiss(self):
        """Celebration screen before closing overlay."""
        if not self.is_active or not self.window:
            return

        logger.info("Penalty cleared! Displaying victory screen.")
        if self._flash_job:
            try:
                self.window.after_cancel(self._flash_job)
            except Exception:
                pass

        emerald = "#00FF88"
        if hasattr(self, "top_border") and self.top_border.winfo_exists():
            self.top_border.configure(bg=emerald)
        if hasattr(self, "bot_border") and self.bot_border.winfo_exists():
            self.bot_border.configure(bg=emerald)
        if hasattr(self, "header_canvas") and self.header_canvas.winfo_exists():
            self.header_canvas.configure(bg="#052014")

        if self.banner_label and self.banner_label.winfo_exists():
            self.banner_label.configure(
                text="🎯  PENALTY CLEARED // ACCESS RESTORED  🎯",
                bg="#052014",
                fg=emerald,
            )

        if self.rep_count_label and self.rep_count_label.winfo_exists():
            self.rep_count_label.configure(
                text=f"{self.target_reps} / {self.target_reps}",
                fg=emerald,
            )

        if self.rep_rem_label and self.rep_rem_label.winfo_exists():
            self.rep_rem_label.configure(
                text="MISSION OBJECTIVE ACHIEVED! UNLOCKING DESKTOP IN 2 SECONDS...",
                fg=emerald,
            )

        if hasattr(self, "prog_canvas") and self.prog_canvas.winfo_exists():
            c_w = self.prog_canvas.winfo_width()
            self.prog_canvas.coords(self._prog_fill_id, 0, 0, c_w, 20)
            self.prog_canvas.itemconfig(self._prog_fill_id, fill=emerald)

        if self.quote_label and self.quote_label.winfo_exists():
            self.quote_label.configure(
                text='"Attention! Penalty cleared! Now lock in and do not let me catch your eyes wandering again! Dismissed!"',
                fg="#aaffbb",
            )

        # Automatically dismiss overlay after 2.5 seconds
        self.window.after(2500, lambda: self.dismiss(victory=True))

    def dismiss(self, victory: bool = False):
        """Dismiss overlay and restore screen control."""
        if not self.is_active:
            return

        self.is_active = False
        if self._flash_job and self.window:
            try:
                self.window.after_cancel(self._flash_job)
            except Exception:
                pass

        if self.window:
            try:
                self.window.grab_release()
            except Exception:
                pass
            self.window.destroy()
            self.window = None
            logger.info("Overlay dismissed. Screen restored.")
