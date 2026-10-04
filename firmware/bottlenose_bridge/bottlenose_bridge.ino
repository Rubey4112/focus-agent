/*
 * Bottlenose Orca / ESP32 Wireless Bridge for Free-Wili OG
 * 
 * Hardware:
 *   - Target: Bottlenose Orca (ESP32-C6) or generic ESP32 / ESP32-C3
 *   - UART Connection to FreeWili OG Breakout Header:
 *       FreeWili Pin 9 (GPIO 8 / UART1 TX)  -> ESP32 RX (e.g. GPIO 17 on C6)
 *       FreeWili Pin 5 (GPIO 9 / UART1 RX)  -> ESP32 TX (e.g. GPIO 16 on C6)
 *       FreeWili Pin 6 (3.3V)               -> ESP32 3V3
 *       FreeWili Pin 20 (GND)               -> ESP32 GND
 *       * Remember FreeWili Pin 4 (V PINS IN) jumpered to 3.3V
 */

#include <Arduino.h>
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <BLE2902.h>

#define DEVICE_NAME         "FreeWili-FocusAgent"
#define SERVICE_UUID        "19B10000-E8F2-537E-4F6C-D104768A1214"
#define TELEMETRY_CHAR_UUID "19B10001-E8F2-537E-4F6C-D104768A1214"

// Pin configuration for ESP32 UART connected to FreeWili Breakout
#if defined(CONFIG_IDF_TARGET_ESP32C6)
  #define FREEWILI_RX_PIN 17
  #define FREEWILI_TX_PIN 16
#elif defined(CONFIG_IDF_TARGET_ESP32C3)
  #define FREEWILI_RX_PIN 20
  #define FREEWILI_TX_PIN 21
#else
  #define FREEWILI_RX_PIN 16
  #define FREEWILI_TX_PIN 17
#endif

BLEServer *pServer = nullptr;
BLECharacteristic *pTelemetryChar = nullptr;
volatile bool deviceConnected = false;

class ServerCallbacks: public BLEServerCallbacks {
    void onConnect(BLEServer* pServer) override {
        deviceConnected = true;
        Serial.println("[BLE] Laptop connected successfully!");
    }

    void onDisconnect(BLEServer* pServer) override {
        deviceConnected = false;
        Serial.println("[BLE] Laptop disconnected.");
        // Restart advertising immediately so the laptop can reconnect
        pServer->startAdvertising();
        Serial.println("[BLE] Advertising restarted.");
    }
};

class TelemetryCallbacks: public BLECharacteristicCallbacks {
    void onWrite(BLECharacteristic *pCharacteristic) override {
        String rxValue = pCharacteristic->getValue().c_str();
        if (rxValue.length() > 0) {
            Serial.printf("[BLE -> FreeWili]: %s\n", rxValue.c_str());
            // Forward command line to FreeWili Main CPU over UART
            Serial1.println(rxValue);
        }
    }
};

void setup() {
    Serial.begin(115200);
    delay(1000);
    Serial.println("\n=============================================");
    Serial.println("  Bottlenose Orca BLE Bridge Starting");
    Serial.println("=============================================");

    // Initialize UART to FreeWili OG
    Serial1.begin(115200, SERIAL_8N1, FREEWILI_RX_PIN, FREEWILI_TX_PIN);
    Serial.printf("[UART] Listening to FreeWili on RX:%d, TX:%d at 115200 baud\n",
                  FREEWILI_RX_PIN, FREEWILI_TX_PIN);

    // Initialize BLE Device
    BLEDevice::init(DEVICE_NAME);
    pServer = BLEDevice::createServer();
    pServer->setCallbacks(new ServerCallbacks());

    // Create Service & Characteristic (bidirectional telemetry + commands)
    BLEService *pService = pServer->createService(SERVICE_UUID);

    pTelemetryChar = pService->createCharacteristic(
        TELEMETRY_CHAR_UUID,
        BLECharacteristic::PROPERTY_READ     |
        BLECharacteristic::PROPERTY_NOTIFY   |
        BLECharacteristic::PROPERTY_WRITE    |
        BLECharacteristic::PROPERTY_WRITE_NR
    );
    pTelemetryChar->addDescriptor(new BLE2902());
    pTelemetryChar->setCallbacks(new TelemetryCallbacks());
    pTelemetryChar->setValue("{\"status\":\"ready\"}");

    pService->start();

    // Configure Advertising:
    // Split into Primary Advertisement and Scan Response to respect the 31-byte BLE limit!
    BLEAdvertising *pAdvertising = BLEDevice::getAdvertising();

    BLEAdvertisementData advData;
    advData.setFlags(0x06); // General Discoverable + BR/EDR Not Supported
    advData.setCompleteServices(BLEUUID(SERVICE_UUID));
    pAdvertising->setAdvertisementData(advData);

    BLEAdvertisementData scanResponseData;
    scanResponseData.setName(DEVICE_NAME);
    pAdvertising->setScanResponseData(scanResponseData);

    pAdvertising->setMinPreferred(0x06); // 7.5ms interval
    pAdvertising->setMaxPreferred(0x12); // 22.5ms interval

    BLEDevice::startAdvertising();
    Serial.println("[BLE] Advertising active. Ready for laptop connection!");
}

void loop() {
    // Read incoming JSON lines from FreeWili OG
    if (Serial1.available()) {
        String line = Serial1.readStringUntil('\n');
        line.trim();
        if (line.length() > 0) {
            Serial.printf("[FreeWili]: %s\n", line.c_str());

            if (deviceConnected && pTelemetryChar != nullptr) {
                pTelemetryChar->setValue(line.c_str());
                pTelemetryChar->notify();
            }
        }
    }

    delay(2);
}
