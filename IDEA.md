A doom scroll detector that uses computer vision to determine if you are doomscrolling, if so, it will forces you to do jumping jacks.

Doom scorll detection is uses OpenCV and a laptop webcam (TBR: to be resolved) for now.

To ensure that you are doing actual jumping jack, the Free-Wili OG (https://freewili.com/freewili-og.html) will be strapped to your waist and you will be doing jumping jacks with the Free-Wili OG attached to you. The accelerometer is used to determine if you are doing actual jumping jack and the jumping jack counter from the Free-Wili OG is sent to the computer via bluetooth.
Additionally, the Free-Wili will play audio of a military officer berating you for your horrible form or your lack of motivation.


Step 1: Detection
- Use OpenCV to detect if the user is doomscrolling
- If the user is doomscrolling, then proceed to step 2
Step 2: Execution
- Notify the user that they are doomscrolling
- Notify the user that they need to do jumping jacks
- Start the jumping jack counter (the number of jumping jacks to do is TBD but configurable)
- Start the Free-Wili OG
- Start the jumping jack counter
Step 3: Verification
- Check if the user is doing actual jumping jacks
- If the user is doing actual jumping jacks, then notify the user that they are done
- If the user is not doing actual jumping jacks, then notify the user that they need to do more jumping jacks


Todo / Implementation Status:
1. [COMPLETED] Jumping jack detection on Free-Wili OG Display CPU (`wiliOGbsp/apps/focus_agent/display/main.c`): Real-time finite state machine tracking thrust, flight, and landing via LIS3DH accelerometer with visual gauge on ST7789 LCD.
2. [COMPLETED] Free-Wili OG Telemetry Forwarding (`wiliOGbsp/apps/focus_agent/main/main.c` & `common/link/jj_proto.h`): Streams framed jumping jack telemetry across inter-CPU link (UART0) and outputs JSON over Breakout UART1 (GPIO 8/9).
3. [COMPLETED] Bottlenose Orca / ESP32 Wireless Bridge (`firmware/bottlenose_bridge/bottlenose_bridge.ino`): BLE GATT server broadcasting telemetry to laptop.
4. [COMPLETED] Laptop Focus Agent & OpenCV Detector (`agent/doomscroll_detector.py` & `agent/focus_agent.py`): Computer vision posture/phone sentinel with military officer voice reprimands and jump verification.