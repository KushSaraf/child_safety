#include <BLEDevice.h>
#include <BLEUtils.h>
#include <BLEServer.h>

#define TAG_NAME "Child-01"  // Unique name for your child tag

void setup() {
  Serial.begin(115200);
  // Initialize BLE
  BLEDevice::init(TAG_NAME);
  // Create BLE Server
  BLEServer *pServer = BLEDevice::createServer();
  // Start advertising
  BLEAdvertising *pAdvertising = BLEDevice::getAdvertising();
  pAdvertising->start();

  Serial.println("BLE Tag Started!");
}

void loop() {
  // Nothing needed in loop for basic broadcasting
  delay(1000);
}
