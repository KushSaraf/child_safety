import asyncio
from ble_scanner import RSSIStream 

class MissingChildIdentification(Exception):
    pass

class RSSIAnalyzer:
    def __init__(self, threshold=-80, window_size=10):
        self.threshold = threshold
        self.window_size = window_size
        self.rssi_history = []

    def analyze(self, rssi):
        self.rssi_history.append(rssi)
        if len(self.rssi_history) > self.window_size:
            self.rssi_history.pop(0)

        avg_rssi = sum(self.rssi_history) / len(self.rssi_history)

        if avg_rssi < self.threshold:
            raise MissingChildIdentification("🚨 Child possibly out of range!")
        else:
            print("✅ Safe zone\n")


async def main():
    analyzer = RSSIAnalyzer(threshold=-80)
    stream = RSSIStream()

    # Subscribe analyzer to live RSSI updates
    stream.subscribe(lambda rssi: handle_rssi(rssi, analyzer))

    # Run BLE scanning loop
    await stream.start_stream()

def handle_rssi(rssi, analyzer):
    try:
        analyzer.analyze(rssi)
    except MissingChildIdentification as e:
        print(e)

if __name__ == "__main__":
    asyncio.run(main())
