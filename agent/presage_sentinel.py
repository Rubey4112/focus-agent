"""Presage SmartSpectra Focus Sentinel Integration.

Wraps the native Presage Technologies SmartSpectra SDK (via smartspectra_capi)
to detect when the user loses focus on the screen, turns their head away,
slouches/looks down at a phone, or gets distracted by something off-screen.
"""

import ctypes
import logging
import os
import queue
import sys
import threading
import time
from typing import Optional, Tuple, Dict, Any
import numpy as np

logger = logging.getLogger("PresageSentinel")

# Presage SmartSpectra Validation Codes
VALIDATION_OK = 0
VALIDATION_NO_FACE_FOUND = 1
VALIDATION_MULTIPLE_FACES_FOUND = 2
VALIDATION_FACE_NOT_CENTERED = 3
VALIDATION_FACE_SIZE_OUT_OF_RANGE = 4
VALIDATION_TOO_DARK = 5
VALIDATION_TOO_BRIGHT = 6
VALIDATION_CHEST_NOT_VISIBLE = 7
VALIDATION_CAMERA_TUNING = 10
VALIDATION_FRAME_RATE_TOO_LOW = 11
VALIDATION_EXCESSIVE_MOTION = 12
VALIDATION_FACE_TOO_CLOSE = 13
VALIDATION_FACE_TOO_FAR = 14
VALIDATION_FACE_TOO_HIGH = 15
VALIDATION_FACE_TOO_LOW = 16
VALIDATION_FACE_NOT_FORWARD = 17

VALIDATION_HINTS = {
    VALIDATION_OK: "Face centered and focused on screen.",
    VALIDATION_NO_FACE_FOUND: "No face found — user left or looking completely away.",
    VALIDATION_MULTIPLE_FACES_FOUND: "Multiple faces detected.",
    VALIDATION_FACE_NOT_CENTERED: "Face not centered — looking off-screen.",
    VALIDATION_FACE_SIZE_OUT_OF_RANGE: "Face distance out of range.",
    VALIDATION_TOO_DARK: "Lighting too dark on face.",
    VALIDATION_TOO_BRIGHT: "Lighting too bright.",
    VALIDATION_CHEST_NOT_VISIBLE: "Chest not visible.",
    VALIDATION_EXCESSIVE_MOTION: "Excessive motion — user distracted / fidgeting.",
    VALIDATION_FACE_TOO_CLOSE: "Face too close to camera.",
    VALIDATION_FACE_TOO_FAR: "Face too far from camera.",
    VALIDATION_FACE_TOO_HIGH: "Face too high.",
    VALIDATION_FACE_TOO_LOW: "Face tilted down — lap phone / doomscroll posture.",
    VALIDATION_FACE_NOT_FORWARD: "Head turned away — user distracted from screen.",
}

# Distraction-triggering validation codes
DISTRACTION_CODES = {
    VALIDATION_FACE_NOT_FORWARD: "HEAD TURNED AWAY (OFF-SCREEN)",
    VALIDATION_FACE_TOO_LOW: "HEAD DOWN / LAP PHONE",
    VALIDATION_FACE_NOT_CENTERED: "FACE DRIFTED OFF-CENTER",
    VALIDATION_NO_FACE_FOUND: "USER ABSENT / NOT AT SCREEN",
    VALIDATION_EXCESSIVE_MOTION: "EXCESSIVE RESTLESS MOTION",
}


class SmartSpectraError(ctypes.Structure):
    _fields_ = [
        ("code", ctypes.c_int),
        ("message", ctypes.c_char * 512),
        ("retryable", ctypes.c_int),
    ]


class SmartSpectraConfig(ctypes.Structure):
    _fields_ = [
        ("api_key", ctypes.c_char_p),
        ("requested_metrics", ctypes.POINTER(ctypes.c_int32)),
        ("requested_metrics_len", ctypes.c_int),
        ("enable_accumulated_output", ctypes.c_int),
        ("log_level", ctypes.c_int),
        ("struct_size", ctypes.c_uint32),
        ("disable_telemetry", ctypes.c_int),
        ("reserved0", ctypes.c_int),
    ]


ON_STATUS_FN = ctypes.CFUNCTYPE(None, ctypes.c_size_t, ctypes.c_int)
ON_VALIDATION_FN = ctypes.CFUNCTYPE(
    None, ctypes.c_size_t, ctypes.c_int, ctypes.c_char_p, ctypes.c_int64
)
ON_METRICS_FN = ctypes.CFUNCTYPE(
    None, ctypes.c_size_t, ctypes.POINTER(ctypes.c_uint8), ctypes.c_int, ctypes.c_int64
)
ON_ERROR_FN = ctypes.CFUNCTYPE(
    None, ctypes.c_size_t, ctypes.c_int, ctypes.c_char_p, ctypes.c_int
)
ON_FRAME_FN = ctypes.CFUNCTYPE(None, ctypes.c_size_t, ctypes.c_int, ctypes.c_int64)


class SmartSpectraCallbacks(ctypes.Structure):
    _fields_ = [
        ("on_status", ON_STATUS_FN),
        ("on_validation", ON_VALIDATION_FN),
        ("on_metrics", ON_METRICS_FN),
        ("on_error", ON_ERROR_FN),
        ("on_frame", ON_FRAME_FN),
        ("on_accumulated_metrics", ctypes.c_void_p),
        ("on_insight", ctypes.c_void_p),
        ("on_video_output", ctypes.c_void_p),
    ]


def locate_smartspectra_dir() -> Optional[str]:
    """Locate the directory containing smartspectra_capi.dll."""
    candidates = []
    base_dir = getattr(sys, "_MEIPASS", None)
    if base_dir:
        candidates.extend([
            os.path.join(base_dir, "smartspectra"),
            os.path.join(base_dir, "agent", "smartspectra"),
            base_dir,
        ])
    here = os.path.dirname(os.path.abspath(__file__))
    candidates.extend([
        os.path.join(here, "smartspectra"),
        os.path.join(here, "..", "smartspectra"),
        os.path.join(os.getcwd(), "agent", "smartspectra"),
        os.path.join(os.getcwd(), "smartspectra"),
        os.getcwd(),
    ])
    for cand in candidates:
        dll_path = os.path.join(cand, "smartspectra_capi.dll")
        if os.path.isfile(dll_path):
            return os.path.abspath(cand)
    return None


def locate_graph_dir() -> Optional[str]:
    """Locate the directory containing graph/metrics_cpu_continuous_rest.binarypb."""
    candidates = []
    base_dir = getattr(sys, "_MEIPASS", None)
    if base_dir:
        candidates.extend([
            os.path.join(base_dir, "smartspectra"),
            os.path.join(base_dir, "agent", "smartspectra"),
            base_dir,
        ])
    here = os.path.dirname(os.path.abspath(__file__))
    candidates.extend([
        os.path.join(here, "smartspectra"),
        os.path.join(here, "..", "smartspectra"),
        os.path.join(os.getcwd(), "agent", "smartspectra"),
        os.path.join(os.getcwd(), "smartspectra"),
        os.getcwd(),
    ])
    for cand in candidates:
        graph_file = os.path.join(cand, "graph", "metrics_cpu_continuous_rest.binarypb")
        if os.path.isfile(graph_file):
            return os.path.abspath(cand)
    return None


_DLL_DIRECTORY_COOKIES = []


class PresageSentinel:
    """Real-time Focus & Distraction Sentinel powered by Presage SmartSpectra."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        distraction_debounce_sec: float = 3.0,
        enabled: bool = True,
    ):
        if not api_key:
            try:
                from settings_manager import get_default_api_key
                api_key = get_default_api_key()
            except Exception:
                api_key = os.getenv("PRESAGE_API_KEY") or os.getenv("SMARTSPECTRA_API_KEY") or ""
        self.api_key = (api_key or "").strip()
        self.distraction_debounce_sec = distraction_debounce_sec
        self.enabled = enabled

        self.dll_dir = locate_smartspectra_dir()
        self.graph_dir = locate_graph_dir()
        self.capi = None
        self.session = None
        self.is_running = False
        self.last_error_message: Optional[str] = None

        # State tracking
        self.last_status_code = 0
        self.last_validation_code = VALIDATION_OK
        self.last_validation_hint = "Initializing"
        self.last_validation_time = 0.0

        # Distraction tracking
        self.is_distracted = False
        self.distraction_start_time: Optional[float] = None
        self.distraction_duration = 0.0
        self.distraction_reason = ""
        self.consecutive_distracted_frames = 0
        self.consecutive_focused_frames = 0

        # Physiological telemetry
        self.latest_pulse_rate: Optional[float] = None
        self.latest_breathing_rate: Optional[float] = None
        self.latest_hrv_rmssd: Optional[float] = None

        # Lock & Worker queue for async frame pushing
        self._lock = threading.Lock()
        self._frame_queue = queue.Queue(maxsize=3)
        self._worker_thread: Optional[threading.Thread] = None
        self._worker_stop = threading.Event()

        # Callbacks keep-alive references
        self._cbs_instance = None
        self._on_status_cb = None
        self._on_val_cb = None
        self._on_met_cb = None
        self._on_err_cb = None
        self._on_fr_cb = None

        if self.enabled:
            self._initialize_sdk()

    def _initialize_sdk(self):
        """Load DLL and preconfigure SDK."""
        self.last_error_message = None
        if not self.dll_dir:
            self.last_error_message = "Presage SmartSpectra directory not found."
            logger.warning("Presage SmartSpectra directory not found. Presage disabled.")
            return

        # Add all relevant candidate directories to Windows DLL search path
        dirs_to_add = set()
        dirs_to_add.add(self.dll_dir)
        base_dir = getattr(sys, "_MEIPASS", None)
        if base_dir:
            dirs_to_add.add(base_dir)
            dirs_to_add.add(os.path.join(base_dir, "smartspectra"))
            dirs_to_add.add(os.path.join(base_dir, "agent", "smartspectra"))
        here = os.path.dirname(os.path.abspath(__file__))
        dirs_to_add.add(here)
        dirs_to_add.add(os.path.join(here, "smartspectra"))

        for d in dirs_to_add:
            if os.path.isdir(d):
                try:
                    cookie = os.add_dll_directory(d)
                    _DLL_DIRECTORY_COOKIES.append(cookie)
                except Exception:
                    pass
                if d not in os.environ.get("PATH", ""):
                    os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")

        dll_path = os.path.join(self.dll_dir, "smartspectra_capi.dll")
        try:
            self.capi = ctypes.CDLL(dll_path)
            self._setup_capi_signatures()
        except Exception as e:
            logger.error(f"Failed to load smartspectra_capi: {e}", exc_info=True)
            self.last_error_message = f"Failed to load smartspectra_capi.dll: {e}"
            self.capi = None
            return

        # Preconfigure persistent state directory in AppData
        try:
            appdata = os.getenv("APPDATA") or os.path.expanduser("~")
            state_dir = os.path.join(appdata, "FreeWiliFocusAgent", "presage_state")
            os.makedirs(state_dir, exist_ok=True)
            err = SmartSpectraError()
            ret = self.capi.smartspectra_preconfigure(
                state_dir.encode("utf-8"), b"FocusAgentDesktop", ctypes.byref(err)
            )
            if ret != 0:
                logger.warning(
                    f"smartspectra_preconfigure warning: code={err.code} msg={err.message.decode(errors='ignore')}"
                )
            else:
                logger.info(f"Presage SmartSpectra preconfigured successfully (state: {state_dir}).")
        except Exception as e:
            logger.warning(f"Optional smartspectra_preconfigure warning: {e}")

    def _setup_capi_signatures(self):
        """Define argument and return types for the C ABI functions."""
        self.capi.smartspectra_preconfigure.argtypes = [
            ctypes.c_char_p,
            ctypes.c_char_p,
            ctypes.POINTER(SmartSpectraError),
        ]
        self.capi.smartspectra_preconfigure.restype = ctypes.c_int

        self.capi.smartspectra_session_create.argtypes = [
            ctypes.POINTER(SmartSpectraConfig),
            ctypes.c_size_t,
            ctypes.POINTER(SmartSpectraCallbacks),
            ctypes.POINTER(SmartSpectraError),
        ]
        self.capi.smartspectra_session_create.restype = ctypes.c_void_p

        self.capi.smartspectra_session_start_custom.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.POINTER(SmartSpectraError),
        ]
        self.capi.smartspectra_session_start_custom.restype = ctypes.c_int

        self.capi.smartspectra_session_send_frame.argtypes = [
            ctypes.c_void_p,
            ctypes.c_char_p,
            ctypes.c_size_t,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int64,
            ctypes.POINTER(SmartSpectraError),
        ]
        self.capi.smartspectra_session_send_frame.restype = ctypes.c_int

        self.capi.smartspectra_session_stop.argtypes = [ctypes.c_void_p]
        self.capi.smartspectra_session_destroy.argtypes = [ctypes.c_void_p]

    def start_session(self) -> bool:
        """Create and start a real-time custom-input SmartSpectra session."""
        if not self.capi:
            self.last_error_message = self.last_error_message or "SmartSpectra native library (smartspectra_capi.dll) is not loaded."
            return False
        if not self.api_key:
            self.last_error_message = "Presage API key is empty."
            return False

        if self.is_running:
            return True

        try:
            @ON_STATUS_FN
            def _on_status(handle, status):
                with self._lock:
                    self.last_status_code = status

            @ON_VALIDATION_FN
            def _on_validation(handle, code, hint, ts):
                hint_str = hint.decode("utf-8", errors="ignore") if hint else ""
                now = time.time()
                with self._lock:
                    self.last_validation_code = code
                    self.last_validation_hint = hint_str
                    self.last_validation_time = now

                    # Distraction evaluation
                    if code in DISTRACTION_CODES:
                        self.consecutive_distracted_frames += 1
                        self.consecutive_focused_frames = 0
                        reason = DISTRACTION_CODES[code]
                        if self.distraction_start_time is None:
                            self.distraction_start_time = now
                            self.distraction_reason = reason
                        self.distraction_duration = now - self.distraction_start_time
                        if self.distraction_duration >= self.distraction_debounce_sec:
                            self.is_distracted = True
                    elif code == VALIDATION_OK:
                        self.consecutive_focused_frames += 1
                        # Require 2 stable focused frames before clearing distraction
                        if self.consecutive_focused_frames >= 2:
                            self.consecutive_distracted_frames = 0
                            self.distraction_start_time = None
                            self.distraction_duration = 0.0
                            self.distraction_reason = ""
                            self.is_distracted = False

            @ON_METRICS_FN
            def _on_metrics(handle, buf, length, ts):
                if not buf or length <= 0:
                    return
                try:
                    # Attempt protobuf decoding if available
                    data_bytes = ctypes.string_at(buf, length)
                    sys.path.insert(0, self.dll_dir)
                    import metrics_pb2
                    metrics = metrics_pb2.Metrics()
                    metrics.ParseFromString(data_bytes)
                    with self._lock:
                        if metrics.HasField("cardio"):
                            if len(metrics.cardio.pulse_rate) > 0:
                                self.latest_pulse_rate = metrics.cardio.pulse_rate[-1].value
                            if len(metrics.cardio.hrv) > 0:
                                self.latest_hrv_rmssd = metrics.cardio.hrv[-1].rmssd
                        if metrics.HasField("breathing"):
                            if len(metrics.breathing.rate) > 0:
                                self.latest_breathing_rate = metrics.breathing.rate[-1].value
                except Exception:
                    pass

            @ON_ERROR_FN
            def _on_error(handle, code, msg, ret):
                err_msg = msg.decode("utf-8", errors="ignore") if msg else ""
                logger.error(f"SmartSpectra Runtime Error [{code}]: {err_msg}")
                self.last_error_message = f"Runtime Error [{code}]: {err_msg}"

            @ON_FRAME_FN
            def _on_frame(handle, sent, ts):
                pass

            self._on_status_cb = _on_status
            self._on_val_cb = _on_validation
            self._on_met_cb = _on_metrics
            self._on_err_cb = _on_error
            self._on_fr_cb = _on_frame

            cbs = SmartSpectraCallbacks()
            cbs.on_status = _on_status
            cbs.on_validation = _on_validation
            cbs.on_metrics = _on_metrics
            cbs.on_error = _on_error
            cbs.on_frame = _on_frame
            self._cbs_instance = cbs

            cfg = SmartSpectraConfig()
            cfg.api_key = self.api_key.encode("utf-8")
            cfg.requested_metrics = None
            cfg.requested_metrics_len = 0
            cfg.enable_accumulated_output = 0
            cfg.log_level = 0
            cfg.struct_size = ctypes.sizeof(SmartSpectraConfig)
            cfg.disable_telemetry = 0

            err = SmartSpectraError()
            self.session = self.capi.smartspectra_session_create(
                ctypes.byref(cfg), 0, ctypes.byref(cbs), ctypes.byref(err)
            )
            if not self.session:
                msg = err.message.decode(errors="ignore") if err.message else f"Code {err.code}"
                self.last_error_message = f"Presage cloud authentication failed ({err.code}): {msg}"
                logger.error(self.last_error_message)
                return False

            # Switch CWD temporarily so graph/models are found by CalculatorGraph
            run_dir = self.graph_dir or self.dll_dir
            old_cwd = os.getcwd()
            os.chdir(run_dir)
            try:
                res = self.capi.smartspectra_session_start_custom(
                    self.session, 0, ctypes.byref(err)
                )
            finally:
                os.chdir(old_cwd)

            if res != 0:
                msg = err.message.decode(errors="ignore") if err.message else f"Code {err.code}"
                self.last_error_message = f"Presage pipeline graph start failed ({err.code}): {msg}"
                logger.error(self.last_error_message)
                self.capi.smartspectra_session_destroy(self.session)
                self.session = None
                return False

            self.is_running = True
            self._worker_stop.clear()
            self._worker_thread = threading.Thread(
                target=self._frame_pusher_worker, daemon=True
            )
            self._worker_thread.start()
            logger.info("Presage SmartSpectra session active and streaming.")
            return True

        except Exception as e:
            self.last_error_message = f"Exception starting Presage session: {e}"
            logger.error(self.last_error_message, exc_info=True)
            return False

    def _frame_pusher_worker(self):
        """Worker thread to push frames asynchronously into SmartSpectra."""
        err = SmartSpectraError()
        t0 = time.monotonic()
        frame_idx = 0
        while not self._worker_stop.is_set():
            try:
                frame_data = self._frame_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            if frame_data is None:
                break

            frame_bytes, w, h, stride = frame_data
            frame_idx += 1
            ts_us = int((time.monotonic() - t0) * 1_000_000)

            try:
                self.capi.smartspectra_session_send_frame(
                    self.session,
                    frame_bytes,
                    len(frame_bytes),
                    w,
                    h,
                    stride,
                    1,  # PixelFormat: BGR = 1
                    ts_us,
                    ctypes.byref(err),
                )
            except Exception:
                pass

    def push_frame(self, frame: np.ndarray):
        """Queue a camera frame for asynchronous SmartSpectra processing."""
        if not self.is_running or self.session is None:
            return

        h, w = frame.shape[:2]
        # Drop oldest frame if queue full to preserve low latency
        if self._frame_queue.full():
            try:
                self._frame_queue.get_nowait()
            except queue.Empty:
                pass

        try:
            # Send contiguous BGR bytes
            raw_bytes = frame.tobytes()
            stride = w * 3
            self._frame_queue.put_nowait((raw_bytes, w, h, stride))
        except Exception:
            pass

    def stop_session(self):
        """Stop and tear down the session."""
        if not self.is_running:
            return

        self.is_running = False
        self._worker_stop.set()
        try:
            self._frame_queue.put_nowait(None)
        except Exception:
            pass

        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=1.0)
            self._worker_thread = None

        if self.session and self.capi:
            try:
                self.capi.smartspectra_session_stop(self.session)
                self.capi.smartspectra_session_destroy(self.session)
            except Exception:
                pass
            self.session = None

        with self._lock:
            self.distraction_start_time = None
            self.distraction_duration = 0.0
            self.is_distracted = False
            self.distraction_reason = ""

        logger.info("Presage SmartSpectra session stopped.")

    def reset_penalty(self):
        """Reset distraction accumulation when penalty is resolved."""
        with self._lock:
            self.distraction_start_time = None
            self.distraction_duration = 0.0
            self.is_distracted = False
            self.distraction_reason = ""
            self.consecutive_distracted_frames = 0

    def get_telemetry(self) -> Dict[str, Any]:
        """Fetch snapshot of real-time Presage telemetry."""
        with self._lock:
            return {
                "enabled": self.enabled,
                "is_running": self.is_running,
                "status_code": self.last_status_code,
                "validation_code": self.last_validation_code,
                "validation_hint": self.last_validation_hint,
                "is_distracted": self.is_distracted,
                "distraction_duration": self.distraction_duration,
                "distraction_reason": self.distraction_reason,
                "pulse_rate": self.latest_pulse_rate,
                "breathing_rate": self.latest_breathing_rate,
                "hrv_rmssd": self.latest_hrv_rmssd,
            }
