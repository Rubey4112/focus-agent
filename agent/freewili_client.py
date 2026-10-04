"""FreeWili Telemetry & Control Client.

Supports:
1. Bluetooth Low Energy (BLE) via Bleak to Bottlenose Orca (ESP32)
2. USB CDC Serial via PySerial (direct wired FreeWili connection)
3. Simulated mode for testing without hardware
"""

import asyncio
import json
import logging
import threading
import time
from typing import Callable, Optional, Dict, Any

logger = logging.getLogger("FreeWiliClient")

# Focus Agent BLE UUIDs (matches bottlenose_bridge.ino)
SERVICE_UUID = "19b10000-e8f2-537e-4f6c-d104768a1214"
TELEMETRY_CHAR_UUID = "19b10001-e8f2-537e-4f6c-d104768a1214"
DEVICE_NAME = "FreeWili-FocusAgent"

STATE_NAMES = {
    0: "IDLE",
    1: "DIP",
    2: "THRUST",
    3: "FLIGHT",
    4: "LANDED",
}


class FreeWiliTelemetry:
    def __init__(self, jumps: int = 0, target: int = 20, state: int = 0, g_mg: int = 1000, peak_mg: int = 0):
        self.jumps = jumps
        self.target = target
        self.state = state
        self.state_name = STATE_NAMES.get(state, "UNKNOWN")
        self.g_mg = g_mg
        self.peak_mg = peak_mg
        self.peak_g_mg = peak_mg
        self.timestamp = time.time()

    @classmethod
    def from_json(cls, text: str) -> Optional["FreeWiliTelemetry"]:
        try:
            data = json.loads(text)
            return cls(
                jumps=int(data.get("jumps", 0)),
                target=int(data.get("target", 20)),
                state=int(data.get("state", 0)),
                g_mg=int(data.get("g_mg", 1000)),
                peak_mg=int(data.get("peak_mg", 0)),
            )
        except Exception:
            return None

    def __repr__(self) -> str:
        return f"<FreeWiliTelemetry jumps={self.jumps}/{self.target} state={self.state_name} g={self.g_mg}mg peak={self.peak_mg}mg>"


class FreeWiliClient:
    def __init__(self, on_telemetry: Optional[Callable[[FreeWiliTelemetry], None]] = None):
        self.on_telemetry = on_telemetry
        self.latest_telemetry = FreeWiliTelemetry()
        self.is_connected = False
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._ble_queue: Optional[asyncio.Queue] = None
        self._ser = None
        self._mode = "none"

    def _handle_payload(self, text: str):
        if not text:
            return
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            if line.startswith("{"):
                t = FreeWiliTelemetry.from_json(line)
                if t:
                    self.latest_telemetry = t
                    if self.on_telemetry:
                        self.on_telemetry(t)
            elif line.startswith("[telemetry]"):
                try:
                    parts = dict(kv.split("=") for kv in line.replace("[telemetry] ", "").split())
                    t = FreeWiliTelemetry(
                        jumps=int(parts.get("jumps", 0)),
                        target=int(parts.get("target", 20)),
                        state=int(parts.get("state", 0)),
                        g_mg=int(parts.get("g", 1000)),
                        peak_mg=int(parts.get("peak", 0)),
                    )
                    self.latest_telemetry = t
                    if self.on_telemetry:
                        self.on_telemetry(t)
                except Exception:
                    pass

    # -------------------------------------------------------------
    # Command Dispatch (Target Sync & Audio Triggers)
    # -------------------------------------------------------------
    def send_command(self, cmd: Dict[str, Any]):
        """Send a JSON command packet to the FreeWili."""
        msg = json.dumps(cmd) + "\n"
        logger.info(f"Dispatching command to FreeWili: {cmd}")

        if self._mode == "ble" and self._loop and self._ble_queue:
            self._loop.call_soon_threadsafe(self._ble_queue.put_nowait, msg.encode("utf-8"))
        elif self._mode == "serial" and self._ser:
            try:
                self._ser.write(msg.encode("utf-8"))
                self._ser.flush()
            except Exception as e:
                logger.warning(f"Serial write error: {e}")
        elif self._mode == "mock":
            if "target" in cmd:
                self.latest_telemetry.target = int(cmd["target"])
                self.latest_telemetry.jumps = 0
            logger.info(f"[Mock FreeWili] Executed command: {cmd}")

    def set_target(self, target: int):
        """Sync jumping jack target goal to FreeWili screen & counter."""
        self.send_command({"cmd": "set_target", "target": target})

    def play_sound(self, sound_id: int):
        """Trigger military audio on FreeWili I2S speaker (1=Swivel, 2=Planet, 3=Boots, 4=Slugs, 5=Cleared)."""
        self.send_command({"cmd": "play_sound", "sound": sound_id})

    def set_volume(self, volume: int):
        """Adjust speaker volume on FreeWili I2S amplifier (0-100%)."""
        self.send_command({"cmd": "set_volume", "volume": max(0, min(100, volume))})

    # -------------------------------------------------------------
    # BLE Connection Mode (Bottlenose Orca)
    # -------------------------------------------------------------
    def start_ble(self):
        """Start BLE listener in background thread."""
        self._mode = "ble"
        self._running = True
        self._thread = threading.Thread(target=self._run_ble_loop, daemon=True)
        self._thread.start()

    def _run_ble_loop(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._ble_queue = asyncio.Queue()
        self._loop.run_until_complete(self._ble_worker())

    async def _ble_worker(self):
        try:
            from bleak import BleakScanner, BleakClient
        except ImportError:
            logger.error("bleak is not installed. Please run 'pip install bleak'.")
            return

        logger.info(f"Scanning for BLE device '{DEVICE_NAME}'...")
        while self._running:
            device = await BleakScanner.find_device_by_name(DEVICE_NAME, timeout=10.0)
            if not device:
                logger.info("Device not found. Retrying scan in 3s...")
                await asyncio.sleep(3.0)
                continue

            logger.info(f"Connecting to {device.address}...")
            try:
                async with BleakClient(device, timeout=15.0) as client:
                    self.is_connected = True
                    logger.info(f"Connected to Bottlenose Orca! (MTU: {client.mtu_size})")

                    def notification_handler(sender, data: bytearray):
                        text = data.decode("utf-8", errors="ignore").strip()
                        self._handle_payload(text)

                    await client.start_notify(TELEMETRY_CHAR_UUID, notification_handler)

                    # Send initial sync command if available
                    if self.latest_telemetry.target > 0:
                        init_cmd = json.dumps({"cmd": "set_target", "target": self.latest_telemetry.target}) + "\n"
                        await client.write_gatt_char(TELEMETRY_CHAR_UUID, init_cmd.encode("utf-8"))

                    # Main loop draining command queue and receiving notifications
                    while self._running and client.is_connected:
                        try:
                            # Check for outbound commands to FreeWili
                            cmd_data = await asyncio.wait_for(self._ble_queue.get(), timeout=0.2)
                            await client.write_gatt_char(TELEMETRY_CHAR_UUID, cmd_data)
                            logger.info(f"[BLE Sent]: {cmd_data.decode().strip()}")
                        except asyncio.TimeoutError:
                            pass

                    await client.stop_notify(TELEMETRY_CHAR_UUID)
            except Exception as e:
                logger.warning(f"BLE connection lost or error: {e}")
            finally:
                self.is_connected = False
                await asyncio.sleep(2.0)

    # -------------------------------------------------------------
    # Serial Connection Mode (Direct USB CDC or USB-UART)
    # -------------------------------------------------------------
    def start_serial(self, port: str, baud: int = 115200):
        """Start USB Serial listener in background thread."""
        self._mode = "serial"
        self._running = True
        self._thread = threading.Thread(target=self._serial_worker, args=(port, baud), daemon=True)
        self._thread.start()

    def _serial_worker(self, port: str, baud: int):
        try:
            import serial
        except ImportError:
            logger.error("pyserial is not installed. Please run 'pip install pyserial'.")
            return

        while self._running:
            try:
                logger.info(f"Opening serial port {port} at {baud} baud...")
                with serial.Serial(port, baud, timeout=1.0) as ser:
                    self._ser = ser
                    self.is_connected = True
                    logger.info("Connected to FreeWili serial port!")

                    # Sync initial target
                    if self.latest_telemetry.target > 0:
                        init_cmd = json.dumps({"cmd": "set_target", "target": self.latest_telemetry.target}) + "\n"
                        ser.write(init_cmd.encode("utf-8"))

                    while self._running:
                        line = ser.readline().decode("utf-8", errors="ignore").strip()
                        if line:
                            if line.startswith("{"):
                                self._handle_payload(line)
                            elif line.startswith("[telemetry]"):
                                try:
                                    parts = dict(kv.split("=") for kv in line.replace("[telemetry] ", "").split())
                                    t = FreeWiliTelemetry(
                                        jumps=int(parts.get("jumps", 0)),
                                        target=int(parts.get("target", 20)),
                                        state=int(parts.get("state", 0)),
                                        g_mg=int(parts.get("g", 1000)),
                                        peak_mg=int(parts.get("peak", 0)),
                                    )
                                    self.latest_telemetry = t
                                    if self.on_telemetry:
                                        self.on_telemetry(t)
                                except Exception:
                                    pass
            except Exception as e:
                logger.warning(f"Serial port error: {e}")
                self.is_connected = False
                self._ser = None
                time.sleep(2.0)

    # -------------------------------------------------------------
    # Simulated Mode (No Hardware Needed)
    # -------------------------------------------------------------
    def start_mock(self, jumps_per_min: float = 30.0):
        """Mock telemetry generator for testing."""
        self._mode = "mock"
        self._running = True
        self.is_connected = True
        self._thread = threading.Thread(target=self._mock_worker, args=(jumps_per_min,), daemon=True)
        self._thread.start()

    def _mock_worker(self, rate: float):
        count = 0
        interval = 60.0 / rate if rate > 0 else 2.0
        while self._running:
            time.sleep(interval)
            count += 1
            t = FreeWiliTelemetry(jumps=count, target=self.latest_telemetry.target, state=4, g_mg=1850, peak_mg=1950)
            self.latest_telemetry = t
            if self.on_telemetry:
                self.on_telemetry(t)

    def stop(self):
        self._running = False
        self.is_connected = False


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("Testing FreeWiliClient bidirectional messaging with mock generator...")
    client = FreeWiliClient(on_telemetry=lambda t: print(f"Received: {t}"))
    client.start_mock(jumps_per_min=60)
    client.set_target(15)
    client.play_sound(1)
    try:
        time.sleep(4)
    finally:
        client.stop()
