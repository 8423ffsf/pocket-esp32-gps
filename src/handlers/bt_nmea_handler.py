import bluetooth
import time
# 从utils目录导入广播工具
from utils.ble_advertising import advertising_payload
from micropython import const
from machine import Pin
# 从handlers目录导入GPS处理模块
from handlers.gps_handler import GPSHandler

# ==================== BLE核心常量 ====================
_IRQ_CENTRAL_CONNECT = const(1)
_IRQ_CENTRAL_DISCONNECT = const(2)
_IRQ_GATTS_READ_REQUEST = const(4)

_LOCATION_SERVICE_UUID = bluetooth.UUID(0x1819)
_NMEA_CHAR_UUID = bluetooth.UUID(0x2A8E)

_APP_NAME = "ESP32-GNSS-GPS"
_UPDATE_INTERVAL = 2
_PIN_CODE = "1234"

# ==================== BLE NMEA服务类 ====================
class BTNMEAHandler:
    def __init__(self, gps_handler):
        self.gps_handler = gps_handler
        self._ble = bluetooth.BLE()
        self._ble.active(True)
        self._ble.irq(self._irq_handler)
        self._connections = set()

        # 注册BLE服务
        service = (
            _LOCATION_SERVICE_UUID,
            [(_NMEA_CHAR_UUID, bluetooth.FLAG_READ | bluetooth.FLAG_NOTIFY | bluetooth.FLAG_INDICATE)],
        )
        ((self.nmea_handle,),) = self._ble.gatts_register_services([service])
        self._ble.gatts_write(self.nmea_handle, b"")

        # 配置BLE配对
        self._ble.config(
            mitm=True,
            bond=True,
            le_secure=True,
            pin=_PIN_CODE
        )
        self._ble.gap_set_security(
            io=bluetooth.IO_CAP_DISPLAY_ONLY,
            auth=bluetooth.AUTH_BOND | bluetooth.AUTH_MITM
        )

        # 构建广播包
        self._adv_payload = advertising_payload(
            name=_APP_NAME,
            services=[_LOCATION_SERVICE_UUID],
            appearance=0x0541,
            flags=0x06,
        )
        self._start_advertising()

    def _start_advertising(self):
        self._ble.gap_advertise(30000, adv_data=self._adv_payload)
        print(f"[BT-NMEA] Advertising started: {_APP_NAME}")

    def _irq_handler(self, event, data):
        if event == _IRQ_CENTRAL_CONNECT:
            conn_handle, _, _ = data
            print(f"[BT-NMEA] Connected: {conn_handle}")
            if len(self._connections) >= 1:
                for c in self._connections:
                    self._ble.gap_disconnect(c)
                self._connections.clear()
            self._connections.add(conn_handle)

        elif event == _IRQ_CENTRAL_DISCONNECT:
            conn_handle, _, _ = data
            print(f"[BT-NMEA] Disconnected: {conn_handle}")
            self._connections.remove(conn_handle)
            self._start_advertising()

        elif event == _IRQ_GATTS_READ_REQUEST:
            self._update_nmea_data()

    def _update_nmea_data(self):
        try:
            gps_raw = self.gps_handler.gps_data["raw_nmea"]
            # 优先GN前缀，GP兜底
            nmea_lines = [
                gps_raw.get("GNRMC") or gps_raw.get("GPRMC", ""),
                gps_raw.get("GNGGA") or gps_raw.get("GPGGA", "")
            ]
            valid_lines = [line.strip() for line in nmea_lines if line and line.startswith("$")]

            # 无数据时填充占位符
            if not valid_lines:
                valid_lines = [
                    "$GNGGA,000000.00,0000.0000,N,00000.0000,E,0,00,99.99,0.0,M,,M,,*56",
                    "$GNRMC,000000.00,V,0000.0000,N,000000.0000,E,0.0,0.0,010170,,,N*48"
                ]

            nmea_data = "\r\n".join(valid_lines).encode("ascii")
            self._ble.gatts_write(self.nmea_handle, nmea_data)

            for conn_handle in list(self._connections):
                try:
                    self._ble.gatts_notify(conn_handle, self.nmea_handle)
                except Exception:
                    self._connections.remove(conn_handle)
        except Exception as e:
            print(f"[BT-NMEA] Data update error: {e}")

    def run(self):
        last_update = time.ticks_ms()
        while True:
            current_time = time.ticks_ms()
            if time.ticks_diff(current_time, last_update) >= _UPDATE_INTERVAL * 1000:
                self._update_nmea_data()
                last_update = current_time
            if self._connections:
                for conn_handle in list(self._connections):
                    try:
                        self._ble.gatts_notify(conn_handle, self.nmea_handle)
                    except Exception:
                        self._connections.remove(conn_handle)
            time.sleep_ms(100)