import bluetooth
import time
from ble_advertising import advertising_payload
from micropython import const

# 蓝牙GATT常量
_IRQ_CENTRAL_CONNECT = const(1)
_IRQ_CENTRAL_DISCONNECT = const(2)
_IRQ_GATTS_READ_REQUEST = const(4)

# 标准蓝牙服务UUID (位置服务)
_LOCATION_SERVICE_UUID = bluetooth.UUID(0x1819)

# 自定义特征值UUID (用于发送NMEA数据)
_NMEA_CHAR_UUID = bluetooth.UUID(0x2AA0)

# 配对参数
_PIN_CODE = "123456"
_APP_NAME = "ESP32-GPS"
_UPDATE_INTERVAL = 1  # 数据更新间隔(秒)

class BLEGPS:
    def __init__(self):
        self._ble = bluetooth.BLE()
        self._ble.active(True)
        self._ble.irq(self._irq_handler)
        self._connections = set()
        
        # 注册位置服务
        service = (
            _LOCATION_SERVICE_UUID,
            [(_NMEA_CHAR_UUID, bluetooth.FLAG_READ | bluetooth.FLAG_NOTIFY)],
        )
        services = [service]
        ((self.nmea_handle,),) = self._ble.gatts_register_services(services)
        
        # 设置特征值初始值
        self._ble.gatts_write(self.nmea_handle, b"")
        
        # 设置配对安全参数
        self._ble.config(mitm=True, bond=True, le_secure=True)
        self._ble.gap_set_security(io=bluetooth.IO_CAP_DISPLAY_ONLY)
        
        # 设置广播数据
        payload = advertising_payload(
            name=_APP_NAME, 
            services=[_LOCATION_SERVICE_UUID],
            appearance=0x0541  # GPS外观值
        )
        self._ble.gap_advertise(100000, adv_data=payload)

    def _irq_handler(self, event, data):
        if event == _IRQ_CENTRAL_CONNECT:
            conn_handle, _, _ = data
            self._connections.add(conn_handle)
            
        elif event == _IRQ_CENTRAL_DISCONNECT:
            conn_handle, _, _ = data
            self._connections.remove(conn_handle)
            self._ble.gap_advertise(100000)
            
        elif event == _IRQ_GATTS_READ_REQUEST:
            conn_handle, attr_handle = data
            if attr_handle == self.nmea_handle:
                self._update_nmea_data()

    def _update_nmea_data(self):
        """更新NMEA数据并写入特征值"""
        try:
            # 从同事提供的接口获取最新NMEA数据
            gprmc = gps_handler.gps_data["raw_nmea"]["GPRMC"] or ""
            gpgga = gps_handler.gps_data["raw_nmea"]["GPGGA"] or ""
            gpgsv = gps_handler.gps_data["raw_nmea"]["GPGSV"] or ""
            
            # 组合NMEA语句
            nmea_data = f"{gprmc}\n{gpgga}\n{gpgsv}".encode()
            self._ble.gatts_write(self.nmea_handle, nmea_data)
            
        except:
            # 静默处理错误
            pass

    def run(self):
        """主运行循环，处理定时更新"""
        last_update = time.ticks_ms()
        
        while True:
            current_time = time.ticks_ms()
            
            # 定时更新
            if time.ticks_diff(current_time, last_update) >= _UPDATE_INTERVAL * 1000:
                self._update_nmea_data()
                last_update = current_time
            
            time.sleep_ms(100)

# 初始化
ble_gps = BLEGPS()
ble_gps.run()