import asyncio
from bleak import BleakScanner

TARGET_TAG_NAME = "Child-01"
RSSI_THRESHOLD = -80

class RSSIStream:
    def __init__(self):
        self.latest_rssi = None
        self.subscribers = []

    def detection_callback(self, device, advertisement_data):
        if device.name and TARGET_TAG_NAME in device.name:
            rssi = advertisement_data.rssi
            self.latest_rssi = rssi
            print(f"✅ {device.name} RSSI: {rssi} dBm")

            # Notify subscribers (like your analyzer)
            for callback in self.subscribers:
                callback(rssi)

    async def start_stream(self):
        scanner = BleakScanner(self.detection_callback)
        print("🔍 Scanning for nearby BLE devices...")

        while True:
            await scanner.start()
            await asyncio.sleep(8)
            await scanner.stop()

    def subscribe(self, callback):
        """Register a callback that receives RSSI values live."""
        self.subscribers.append(callback)


# Run directly for testing
if __name__ == "__main__":
    stream = RSSIStream()
    asyncio.run(stream.start_stream())