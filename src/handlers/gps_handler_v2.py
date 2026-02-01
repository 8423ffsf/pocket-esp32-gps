# gps_handler.py

import time

from machine import UART, Pin, lightsleep


class GPSHandler:
    def __init__(self, led_handler):
        self.led_handler = led_handler
        # Global variables to store GPS data
        self.gps_data = {
            "fix": "No Fix",
            "lat": 0.0,
            "lon": 0.0,
            "alt": 0,
            "sats": 0,
            "pps": 0,
            "hdop": 0,
            "utc_time": None,
            "utc_date": None,
            "speed_knots": 0.0,
            "course": None,
            "satellites": [],
            "satellites_in_view": 0,
            # 兼容GNSS(ATGM336H)+纯GPS模块 双前缀存储
            "raw_nmea": {
                "GPRMC": None,  # 仅GPS
                "GNRMC": None,  # 通用GNSS
                "GPGGA": None,  # 仅GPS
                "GNGGA": None,  # 通用GNSS
                "OTHER": []     # 其他语句兜底
            }
        }
        self.last_pps_time = None

        # Initialize PPS and GPS power pin
        self.pps_pin = Pin(4, Pin.IN)
        #self.gps_power_pin = Pin(26, Pin.OUT)
        #self.gps_power_pin.value(1)
        # UART object
        self.uart1 = None

        # Cache frequently used methods and objects
        self.uart_readline = self.uart1.readline if self.uart1 else None
        self.led_set_success = self.led_handler.set_success_led
        #self.led_set_warning = self.led_handler.set_warning_led
        self.led_set_error = self.led_handler.set_error_led

        self.update_interval = 1000
        self.DEBUG = False

    def set_update_interval(self, interval_ms):
        self.update_interval = max(interval_ms, 100)  # Minimum interval of 100 ms

    # Initialize UART1 to read from the GPS module
    def init_gps(self):
        self.power_on()
        try:
            self.uart1 = UART(
                1, baudrate=9600, bits=8, parity=None, stop=1, tx=Pin(17), rx=Pin(16)
            )
            if not self.uart1:
                raise ValueError("[ERROR] Failed to initialize UART")
            self.uart_readline = self.uart1.readline
        except Exception as e:
            print(f"[ERROR] UART initialization error: {e}")
            self.uart1 = None
            return

        # Attach interrupt to PPS pin
        self.pps_pin.irq(trigger=Pin.IRQ_RISING, handler=self.pps_handler)
        if self.DEBUG:
            print("[DEBUG] GPS initialized")

    #def power_off(self):
    #    if self.DEBUG:
    #        print("[DEBUG] Powering off GPS")
    #    self.gps_power_pin.value(0)

    def power_on(self):
        print("[DEBUG] Powering on GPS")
        #self.gps_power_pin.value(1)

    # PPS signal handler to measure intervals between pulses
    def pps_handler(self, pin):
        try:
            current_time = time.ticks_us()
            if pin.value() == 1:
                if self.last_pps_time is not None:
                    interval = time.ticks_diff(current_time, self.last_pps_time)
                    self.gps_data["pps"] = interval
                self.last_pps_time = current_time
        except Exception as e:
            print(f"[ERROR] PPS handler error: {e}")

    # Convert DDDMM.MMMM to decimal degrees
    @staticmethod
    @micropython.native
    def convert_to_decimal(degrees_minutes):
        if not (degrees_minutes and degrees_minutes.strip()):
            return None
        try:
            parts = degrees_minutes.split(".")
            if len(parts) != 2 or len(parts[0]) < 3:
                return None
            degrees = float(parts[0][:-2])
            minutes = float(f"{parts[0][-2:]}.{parts[1]}")
            return degrees + (minutes / 60)
        except (ValueError, IndexError):
            print(f"[ERROR] Invalid degree format: {degrees_minutes}")
            return None

    # Read GPS data (全兼容GN/GP双前缀，容错拉满)
    @micropython.native
    def read_gps(self):
        if not self.uart_readline:
            if self.DEBUG:
                print("[DEBUG] UART not initialized!")
            return self.gps_data

        line = self.uart_readline()
        if not line:
            return self.gps_data

        try:
            line_decoded = line.decode("ascii", "ignore").strip()
            if not line_decoded.startswith("$"):
                if self.DEBUG:
                    print(f"[DEBUG] Invalid NMEA sentence: {line_decoded}")
                return

            # 双前缀精准存储，核心语句分存，其余兜底
            nmea_type = line_decoded[1:6]
            if nmea_type in self.gps_data["raw_nmea"].keys():
                self.gps_data["raw_nmea"][nmea_type] = line_decoded
            else:
                self.gps_data["raw_nmea"]["OTHER"].append(line_decoded)
                if len(self.gps_data["raw_nmea"]["OTHER"]) > 10:
                    self.gps_data["raw_nmea"]["OTHER"].pop(0)

            data = line_decoded.split(",")
            gps_data = self.gps_data

            # 1. 兼容 GNRMC / GPRMC 定位+时间+速度解析
            if line_decoded.startswith(("$GPRMC", "$GNRMC")):
                if len(data) < 7:
                    return self.gps_data
                # 定位有效性判断
                fix = data[2] == "A"
                gps_data["fix"] = "Valid" if fix else "No Fix"
                self.led_set_success(1 if fix else 0)
                self.led_set_error(0 if fix else 1)

                if fix:
                    # UTC时间解析（容错）
                    if len(data[1]) >= 6:
                        gps_data["utc_time"] = f"{data[1][:2]}:{data[1][2:4]}:{data[1][4:6]}"
                    # UTC日期解析（容错）
                    if len(data) >=10 and len(data[9])>=6:
                        gps_data["utc_date"] = f"20{data[9][4:6]}-{data[9][2:4]}-{data[9][:2]}"
                    # 经纬度解析（容错+换算）
                    lat = self.convert_to_decimal(data[3])
                    lon = self.convert_to_decimal(data[5])
                    if lat:
                        gps_data["lat"] = lat * (-1 if data[4] == "S" else 1)
                    if lon:
                        gps_data["lon"] = lon * (-1 if data[6] == "W" else 1)
                    # 速度+航向解析（容错）
                    gps_data["speed_knots"] = float(data[7]) if (data[7] and data[7].strip()) else 0.0
                    gps_data["course"] = float(data[8]) if (data[8] and data[8].strip()) else None

            # 2. 兼容 GNGGA / GPGGA 高度+卫星数+精度解析
            elif line_decoded.startswith(("$GPGGA", "$GNGGA")):
                if len(data) < 10:
                    return self.gps_data
                gps_data["alt"] = float(data[9]) if (data[9] and data[9].strip()) else 0.0
                gps_data["sats"] = int(data[7]) if (data[7] and data[7].strip()) else 0
                gps_data["hdop"] = float(data[8]) if (data[8] and data[8].strip()) else None

            # 3. 兼容 GNSV / GPGSV 卫星详情解析（双前缀通用）
            elif line_decoded.startswith(("$GPGSV", "$GNGSV")):
                if len(data) < 4:
                    return self.gps_data
                gps_data["satellites_in_view"] = int(data[3]) if (data[3] and data[3].strip()) else 0
                gps_data["satellites"].clear() # 清空旧数据，避免冗余
                # 批量解析卫星参数（容错）
                for i in range(4, len(data)-3, 4):
                    try:
                        sat_id = data[i].strip()
                        elev = data[i+1].strip()
                        azim = data[i+2].strip()
                        snr_val = data[i+3].strip()
                        if not sat_id:
                            continue
                        gps_data["satellites"].append({
                            "id": int(sat_id),
                            "elevation": int(elev) if elev else None,
                            "azimuth": int(azim) if azim else None,
                            "snr": int(snr_val) if snr_val else None
                        })
                    except (ValueError, IndexError):
                        continue
                        
        except Exception as e:
            print(f"[ERROR] GPS data process failed: {str(e)}")
            if self.DEBUG:
                print(f"[DEBUG] Raw NMEA: {line}")

        # 低功耗延时，防CPU占用过高
        active_sleep = max(self.update_interval - 100, 0)
        low_power_sleep = min(self.update_interval, 100)
        time.sleep_ms(active_sleep)
        if low_power_sleep > 0:
            lightsleep(low_power_sleep)
        if self.DEBUG:
            print(f"[DEBUG] GPS update done, interval: {self.update_interval}ms")
        return self.gps_data
