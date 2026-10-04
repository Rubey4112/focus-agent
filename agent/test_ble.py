"""Diagnostic utility to test BLE connection to Bottlenose Orca / FreeWili-FocusAgent.
"""

import asyncio
import sys
from bleak import BleakScanner, BleakClient

SERVICE_UUID = "19b10000-e8f2-537e-4f6c-d104768a1214"
TELEMETRY_CHAR_UUID = "19b10001-e8f2-537e-4f6c-d104768a1214"
DEVICE_NAME = "FreeWili-FocusAgent"


async def main():
    print("=" * 65)
    print("  Bottlenose Orca / FreeWili BLE Diagnostic Tool")
    print("=" * 65)
    print("Scanning for BLE devices (10 seconds)...")

    devices = await BleakScanner.discover(timeout=10.0, return_adv=True)
    target = None
    target_adv = None

    for d, adv in devices.values():
        name = d.name or adv.local_name or "Unknown"
        services = [str(s).lower() for s in adv.service_uuids]
        if DEVICE_NAME in name or SERVICE_UUID.lower() in services:
            target = d
            target_adv = adv
            print(f"\n--> FOUND TARGET DEVICE: {name} [{d.address}] (RSSI: {adv.rssi} dBm)")
            break
        elif d.name:
            print(f"  - Found other device: {d.name} [{d.address}]")

    if not target:
        print(f"\n[ERROR] Device '{DEVICE_NAME}' was not found in BLE scan.")
        print("Check:")
        print("  1. Is the ESP32 / Bottlenose Orca powered on and running the bridge sketch?")
        print("  2. Did you pair it in Windows Settings? If so, REMOVE/UNPAIR it from Windows Settings.")
        return

    print(f"\nAttempting to connect to {target.address}...")
    try:
        async with BleakClient(target, timeout=15.0) as client:
            print(f"[SUCCESS] Connected: {client.is_connected}")
            print(f"MTU: {client.mtu_size}")

            print("\nDiscovering GATT Services and Characteristics:")
            for s in client.services:
                print(f"  Service: {s.uuid} ({s.description})")
                for c in s.characteristics:
                    print(f"    - Char: {c.uuid} [{','.join(c.properties)}]")

            def on_notify(sender, data: bytearray):
                text = data.decode("utf-8", errors="ignore").strip()
                print(f"[NOTIFICATION RECEIVED]: {text}")

            print(f"\nSubscribing to telemetry characteristic {TELEMETRY_CHAR_UUID}...")
            await client.start_notify(TELEMETRY_CHAR_UUID, on_notify)
            print("Subscribed! Listening for data for 20 seconds (perform a jump or test UART)...")

            for i in range(20):
                await asyncio.sleep(1.0)
                if not client.is_connected:
                    print("[WARNING] Client disconnected unexpectedly.")
                    break

            await client.stop_notify(TELEMETRY_CHAR_UUID)
            print("\nTest completed successfully!")

    except Exception as e:
        print(f"\n[CONNECTION ERROR]: {e}")
        print("\nTroubleshooting tips for Windows:")
        print("1. If you clicked 'Connect' in Windows Settings (Bluetooth & devices), Windows may be")
        print("   stuck trying to pair with it. Go to Windows Settings -> Bluetooth and REMOVE the device.")
        print("2. Power-cycle the ESP32 / Bottlenose Orca.")
        print("3. Re-run this script: python agent/test_ble.py")


if __name__ == "__main__":
    asyncio.run(main())
