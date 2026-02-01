import bluetooth
import time
from utils.ble_advertising import advertising_payload
from micropython import const

# ==================== BLE 核心常量定义 ====================
_IRQ_CENTRAL_CONNECT = const(1)
_IRQ_CENTRAL_DISCONNECT = const(2)
_IRQ_GATTS_READ_REQUEST = const(4)

# 官方标准 UUID（安卓 BLE GPS APP 直接识别）
_LOCATION_SERVICE_UUID = bluetooth.UUID(0x1819)  # 位置服务 UUID
_NMEA_CHAR_UUID = bluetooth.UUID(0x2A8E)        # NMEA 数据特征值 UUID

# BLE 设备配置
_APP_NAME = "ESP32-GNSS-GPS"
_UPDATE_INTERVAL = 2  # 数据推送间隔（秒），平衡实时性与功耗
_PIN_CODE = "1234"    # BLE 配对码

# ==================== BLE NMEA 核心类（无 LED 依赖） ====================
class BtNMEAHandler:
    def __init__(self, gps_handler):
        """
        构造函数：仅接收 GPS 处理器实例，无 LED 依赖
        :param gps_handler: 从 boot.py 传入的 GPSHandler 实例
        """
        self.gps_handler = gps_handler
        self._ble = bluetooth.BLE()
        self._ble.active(False)  # 初始关闭，等待 activate() 激活
        self._ble.irq(self._irq_handler)
        self._connections = set()
        self._nmea_handle = None
        self._adv_payload = None
        self._is_active = False  # 蓝牙激活状态标记

    def _init_ble_services(self):
        """初始化 BLE 服务和广播包（内部调用）"""
        # 注册官方位置服务 + NMEA 特征值
        service = (
            _LOCATION_SERVICE_UUID,
            [(_NMEA_CHAR_UUID, bluetooth.FLAG_READ | bluetooth.FLAG_NOTIFY | bluetooth.FLAG_INDICATE)],
        )
        ((self._nmea_handle,),) = self._ble.gatts_register_services([service])
        self._ble.gatts_write(self._nmea_handle, b"")  # 初始化特征值为空

        # 配置 BLE 安全配对（MITM + 绑定，安卓兼容）
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

        # 构建广播包（带 GPS 设备标识，安卓优先识别）
        self._adv_payload = advertising_payload(
            name=_APP_NAME,
            services=[_LOCATION_SERVICE_UUID],
            appearance=0x0541,  # 标准 GPS 设备外观码
            flags=0x06,         # 纯 BLE 可发现模式
        )

    def activate(self):
        """激活蓝牙：boot.py 调用此方法启动 BLE"""
        if not self._is_active:
            self._ble.active(True)
            self._init_ble_services()
            self._ble.gap_advertise(30000, adv_data=self._adv_payload)
            self._is_active = True
            print(f"[BT-NMEA] 蓝牙已激活 | 设备名：{_APP_NAME} | 配对码：{_PIN_CODE}")

    def deactivate(self):
        """关闭蓝牙：boot.py 省电模式/异常时调用"""
        if self._is_active:
            self._ble.active(False)
            self._connections.clear()
            self._is_active = False
            print(f"[BT-NMEA] 蓝牙已关闭")

    def is_active(self):
        """判断蓝牙是否激活：供 boot.py 状态判断"""
        return self._is_active

    def _irq_handler(self, event, data):
        """BLE 中断处理：连接/断开/读请求"""
        if event == _IRQ_CENTRAL_CONNECT:
            conn_handle, _, _ = data
            # 单客户端连接，避免多设备干扰
            if len(self._connections) >= 1:
                for c in self._connections:
                    self._ble.gap_disconnect(c)
                self._connections.clear()
            self._connections.add(conn_handle)
            print(f"[BT-NMEA] 客户端已连接 | 句柄：{conn_handle}")

        elif event == _IRQ_CENTRAL_DISCONNECT:
            conn_handle, _, _ = data
            self._connections.remove(conn_handle)
            self._ble.gap_advertise(30000, adv_data=self._adv_payload)  # 重新广播
            print(f"[BT-NMEA] 客户端已断开 | 句柄：{conn_handle}")

        elif event == _IRQ_GATTS_READ_REQUEST:
            """安卓读取数据时，主动刷新最新 NMEA"""
            self._update_nmea_data()

    def _update_nmea_data(self):
        """核心：读取 GPS 数据，优先 GN 前缀，GP 兜底，推送安卓"""
        try:
            if not self._is_active or not self._nmea_handle:
                return
            
            gps_raw = self.gps_handler.gps_data["raw_nmea"]
            # 优先 GNRMC/GNGGA（多模 GNSS），无则取 GPRMC/GPGGA（纯 GPS）
            nmea_lines = [
                gps_raw.get("GNRMC") or gps_raw.get("GPRMC", ""),
                gps_raw.get("GNGGA") or gps_raw.get("GPGGA", "")
            ]
            # 过滤空语句，保留标准 NMEA 格式
            valid_lines = [line.strip() for line in nmea_lines if line and line.startswith("$")]

            # 无有效数据时填充占位符，防止安卓 APP 断连
            if not valid_lines:
                valid_lines = [
                    "$GNGGA,000000.00,0000.0000,N,00000.0000,E,0,00,99.99,0.0,M,,M,,*56",
                    "$GNRMC,000000.00,V,0000.0000,N,000000.0000,E,0.0,0.0,010170,,,N*48"
                ]

            # 标准 NMEA 格式打包（\r\n 分隔，ASCII 编码）
            nmea_data = "\r\n".join(valid_lines).encode("ascii")
            self._ble.gatts_write(self._nmea_handle, nmea_data)

            # 主动通知所有已连接客户端
            for conn_handle in list(self._connections):
                try:
                    self._ble.gatts_notify(conn_handle, self._nmea_handle)
                except Exception:
                    self._connections.remove(conn_handle)
        except Exception as e:
            print(f"[BT-NMEA] 数据更新异常: {str(e)}")

    def run(self):
        """BLE 主循环：定时推送数据（可被 boot.py 主循环调度）"""
        last_update = time.ticks_ms()
        while self._is_active:
            current_time = time.ticks_ms()
            if time.ticks_diff(current_time, last_update) >= _UPDATE_INTERVAL * 1000:
                self._update_nmea_data()
                last_update = current_time
            time.sleep_ms(100)
