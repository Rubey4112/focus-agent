# Bottlenose Orca (ESP32) Wireless Bridge

This firmware runs on the **Bottlenose Orca (ESP32-C6)** or any standard ESP32 development board (such as ESP32-C3, ESP32-WROOM, or Seeed Studio XIAO ESP32). It acts as a transparent wireless bridge between the FreeWili OG and your laptop.

## Hardware Wiring

Connect the FreeWili OG breakout header to the ESP32:

| FreeWili OG Breakout Header | Signal | ESP32 / Bottlenose Orca Pin | Notes |
|---|---|---|---|
| **Pin 9** (`GPIO 08`) | UART1 TX | **RX** (e.g. GPIO 17 on C6) | FreeWili data to ESP32 |
| **Pin 5** (`GPIO 09`) | UART1 RX | **TX** (e.g. GPIO 16 on C6) | Optional reverse link |
| **Pin 6** | 3.3V Power | **3V3** | Power supply |
| **Pin 20** | Ground | **GND** | Ground reference |
| **Pin 4** (`V PINS IN`) | IO Rail | Jumper to Pin 6 (3.3V) | Required for FreeWili IO buffers |

## Flashing Instructions

1. Open `bottlenose_bridge.ino` in the Arduino IDE.
2. In Board Manager, install the `esp32` package by Espressif Systems.
3. Select board:
   - For Bottlenose Orca: **ESP32C6 Dev Module**
   - For generic ESP32: **ESP32 Dev Module** or your specific model.
4. Set upload speed to `921600` and select the appropriate COM port.
5. Click **Upload**.

Once running, the board advertises as `FreeWili-FocusAgent` and sends live jumping jack telemetry over Bluetooth Low Energy (BLE) to the laptop.
