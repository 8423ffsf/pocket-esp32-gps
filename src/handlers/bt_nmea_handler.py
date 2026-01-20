import bluetooth
import time
from ble_advertising import advertising_payload
from micropython import const

# BLE GATT核心中断常量
_IRQ_CENTRAL_CONNECT = const(1)
_IRQ_CENTRAL_DISCONNECT = const(2)
_IRQ_GATTS_READ_REQUEST = const(4)

# 蓝牙官方标准UUID（零配置核心，不可改）
_LOCATION_SERVICE_UUID = bluetooth.UUID(0x1819)  # 官方位置服务UUID
_NMEA_CHAR_UUID = bluetooth.UUID(0x2A8E)        # 官方NMEA数据特征值UUID

# 配对+零配置核心参数
_APP_NAME = "ESP32-GPS"
_UPDATE_INTERVAL = 1  # 数据更新间隔(秒)
_PIN_CODE = "1234"    # 配对PIN码（4/6位，用户首次仅需输入一次）

class BLEGPS:
    def __init__(self):
        self._ble = bluetooth.BLE()
        self._ble.active(True)
        self._ble.irq(self._irq_handler)
        self._connections = set()

        # 注册官方位置服务+标准NMEA特征值（零配置核心）
        service = (
            _LOCATION_SERVICE_UUID,
            [(_NMEA_CHAR_UUID, bluetooth.FLAG_READ | bluetooth.FLAG_NOTIFY | bluetooth.FLAG_INDICATE)],
        )
        services = [service]
        ((self.nmea_handle,),) = self._ble.gatts_register_services(services)

        # 初始化特征值为空字节
        self._ble.gatts_write(self.nmea_handle, b"")

        # 核心：配置安卓兼容的BLE安全配对（MITM+绑定+固定PIN）
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

        # 优化广播：保存广播包实例，断开后复用（保留绑定信息）
        self._adv_payload = advertising_payload(
            name=_APP_NAME,
            services=[_LOCATION_SERVICE_UUID],
            appearance=0x0541,  # GPS设备外观标识
            flags=0x06,         # 纯BLE可发现，安卓优先识别
        )
        self._ble.gap_advertise(30000, adv_data=self._adv_payload)

    def _irq_handler(self, event, data):
        if event == _IRQ_CENTRAL_CONNECT:
            conn_handle, _, _ = data
            # 零配置优化：仅允许单客户端连接，避免多设备干扰
            if len(self._connections) >= 1:
                for c in self._connections:
                    self._ble.gap_disconnect(c)
                self._connections.clear()
            self._connections.add(conn_handle)

        elif event == _IRQ_CENTRAL_DISCONNECT:
            conn_handle, _, _ = data
            self._connections.remove(conn_handle)
            # 复用广播包重新广播，保留绑定信息，方便重连
            self._ble.gap_advertise(30000, adv_data=self._adv_payload)

        elif event == _IRQ_GATTS_READ_REQUEST:
            # 主动刷新数据，保证读取的是最新NMEA
            self._update_nmea_data()

    def _update_nmea_data(self):
        """标准化NMEA数据更新，适配安卓零配置解析"""
        try:
            # 读取核心NMEA语句（GPRMC+GPGGA，定位必备）
            gprmc = gps_handler.gps_data["raw_nmea"].get("GPRMC", "") or ""
            gpgga = gps_handler.gps_data["raw_nmea"].get("GPGGA", "") or ""
            # 过滤无效语句，仅保留标准NMEA格式
            valid_nmea = [line for line in [gprmc, gpgga] if line.strip().startswith('$')]
            if not valid_nmea:
                return
            # 标准NMEA-0183格式：\r\n换行+ASCII编码（蓝牙标准）
            nmea_data = "\r\n".join(valid_nmea).encode('ascii')
            self._ble.gatts_write(self.nmea_handle, nmea_data)
            # 手动触发Notify，确保安卓实时接收（ESP32 MicroPython关键优化）
            for conn_handle in list(self._connections):
                try:
                    self._ble.gatts_notify(conn_handle, self.nmea_handle)
                except:
                    self._connections.remove(conn_handle)
        except Exception:
            # 静默处理错误，避免程序崩溃
            pass

    def run(self):
        #主运行循环：定时更新+BLE保活，配对后零配置稳定运行
        last_update = time.ticks_ms()
        while True:
            current_time = time.ticks_ms()
            # 1秒定时更新NMEA数据
            if time.ticks_diff(current_time, last_update) >= _UPDATE_INTERVAL * 1000:
                self._update_nmea_data()
                last_update = current_time
            # BLE保活：防止安卓安全连接超时断开（500ms一次）
            if self._connections:
                for conn_handle in list(self._connections):
                    try:
                        self._ble.gatts_notify(conn_handle, self.nmea_handle)
                    except:
                        self._connections.remove(conn_handle)
            # 降低CPU占用，平衡实时性
            time.sleep_ms(100)

# 初始化并启动BLE GPS服务（配对验证+零配置版本）
ble_gps = BLEGPS()
ble_gps.run()