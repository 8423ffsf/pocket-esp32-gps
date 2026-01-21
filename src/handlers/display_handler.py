from machine import freq, lightsleep, I2C, Pin
import lib.ssd1306 as ssd1306
import gc
import os
import esp32
import esp
import utime
from utils.haversine import haversine

# 注释：地图模式相关导入
# from handlers.vector_map_handler import VectorMap

from handlers.power_management import PowerManager


class DisplayHandler:
    MODES = [
        "GPS Display",
        "Map Display",
        "Distance Calc",
        "Settings",
        "About",
    ]
    SETTINGS_OPTIONS = [
        "Contrast",
        "Invert Display",
        "Power Save Mode",
        "Enable LEDs",
    ]
    DEBUG = False
    # 🌟全局配置：电量刷新频率（单位：秒，可自行修改，建议2~5秒）
    BATT_REFRESH_INTERVAL = 2
    # 电量显示区域坐标（右上角），适配128*64 SSD1306
    BATT_X = 70
    BATT_Y = 0
    BATT_W = 58
    BATT_H = 10

    # 🌟接收adc_handler实例，全局使用
    def __init__(self, gps, led_handler, settings_handler, adc_handler):
        self.gps = gps
        self.i2c, self.display, self.display_power_button = self.initialize_display()

        self.display_power_button = None
        self.led_handler = led_handler
        self.settings_handler = settings_handler
        self.adc_handler = adc_handler  # 保存ADC实例
        self.power_manager = PowerManager(
            self.display,
            self.gps,
            self.settings_handler,
            self.led_handler,
            self,
        )
        self.power_manager.set_display_power_button(self.display_power_button)

        # 电量相关全局变量
        self.prev_batt_volt = None  # 电压缓存
        self.prev_batt_pct = None   # 百分比缓存
        self.last_batt_update = 0   # 最后一次更新时间（毫秒）
        # 初始化时立即采集一次电量
        self._update_battery()

        self.current_mode = 0
        self.settings_index = 0
        self.is_editing = False
        self.point_A = None
        self.point_B = None
        self.prev_lat = None
        self.prev_lon = None
        self.prev_alt = None
        self.prev_hdop = None
        self.apply_display_settings_and_mode()

    def set_display_power_button(self, button):
        self.power_manager.set_display_power_button(button)

    def handle_user_interaction(self):
        self.power_manager.handle_user_interaction()

    @staticmethod
    def initialize_display():
        i2c = I2C(scl=Pin(22), sda=Pin(21))
        display = ssd1306.SSD1306_I2C(128, 64, i2c)
        display_power_button = Pin(13, Pin.IN, Pin.PULL_UP)
        return i2c, display, display_power_button

    def apply_display_settings_and_mode(self):
        self.display.contrast(
            self.settings_handler.get_setting("contrast", "LCD_SETTINGS")
        )
        self.display.invert(self.settings_handler.get_setting("invert", "LCD_SETTINGS"))
        self.enter_mode(self.current_mode)

    # 🌟核心新增：独立电量更新方法，按固定频率采集
    def _update_battery(self):
        current_time = utime.ticks_ms()
        # 达到刷新间隔，才采集新数据
        if utime.ticks_diff(current_time, self.last_batt_update) >= self.BATT_REFRESH_INTERVAL * 1000:
            try:
                self.prev_batt_volt = self.adc_handler.get_voltage()
                self.prev_batt_pct = self.adc_handler.get_battery_percent()
                self.last_batt_update = current_time
            except Exception as e:
                if self.DEBUG:
                    print(f"[BATT ERROR] 采集失败: {e}")
        # 有缓存值则绘制，无则不显示
        if self.prev_batt_volt is not None and self.prev_batt_pct is not None:
            # 局部清屏电量区域，避免文字重叠
            self.display.fill_rect(self.BATT_X, self.BATT_Y, self.BATT_W, self.BATT_H, 0)
            self.display.text(f"{self.prev_batt_volt}V({self.prev_batt_pct}%)", self.BATT_X, self.BATT_Y)

    # 🌟重写enter_mode，界面切换时先更新/绘制电量
    def enter_mode(self, mode):
        print(f"Before check: current_mode={self.current_mode}, requested_mode={mode}")
        self.display.fill(0)
        self.display.show()
        self.current_mode = mode
        mode_functions = {
            0: self.show_main_gps_display,
            1: self.enter_distance_mode,
            2: self.enter_settings_mode,
            3: self.display_about,
        }
        self.led_handler.set_mode_led(1 if mode > 0 else 0)
        mode_functions.get(mode, self.show_main_gps_display)()
        # 界面初始化完成后，绘制电量（防止全局清屏覆盖）
        self._update_battery()
        self.display.show()
        gc.collect()

    def show_main_gps_display(self):
        self.update_gps_display()

    def show_second_gps_display(self):
        self.gps_second_display()
        gc.collect()

    # GPS主界面：移除原有电量逻辑，改用全局_update_battery
    def update_gps_display(self):
        self.display.fill_rect(0, 0, self.BATT_X, self.BATT_H, 0)
        fix_status = self.gps.gps_data.get("fix", "No Fix")
        self.display.text(f"Fix: {fix_status}", 0, 0)

        if fix_status in ["Valid", "Partial"]:
            lat = self.gps.gps_data.get("lat")
            lon = self.gps.gps_data.get("lon")
            alt = self.gps.gps_data.get("alt")
            hdop = self.gps.gps_data.get("hdop")

            if lat != self.prev_lat and lat is not None:
                self.display.fill_rect(0, 20, 128, 10, 0)
                self.display.text(f"Lat: {lat:.6f}", 0, 20)
                self.prev_lat = lat
            elif lat is not None:
                self.display.text(f"Lat: {lat:.6f}", 0, 20)

            if lon != self.prev_lon and lon is not None:
                self.display.fill_rect(0, 30, 128, 10, 0)
                self.display.text(f"Lon: {lon:.6f}", 0, 30)
                self.prev_lon = lon
            elif lon is not None:
                self.display.text(f"Lon: {lon:.6f}", 0, 30)

            if alt != self.prev_alt and alt is not None:
                self.display.fill_rect(0, 40, 128, 10, 0)
                self.display.text(f"Alt: {alt}m", 0, 40)
                self.prev_alt = alt
            elif alt is not None:
                self.display.text(f"Alt: {alt}m", 0, 40)

            if hdop != self.prev_hdop and hdop is not None:
                self.display.fill_rect(0, 50, 128, 10, 0)
                self.display.text(f"HDOP: {hdop:.1f}m", 0, 50)
                self.prev_hdop = hdop
            elif hdop is not None:
                self.display.text(f"HDOP: {hdop:.1f}m", 0, 50)
        else:
            self.display.fill_rect(0, 20, 128, 40, 0)
            self.display.text("Waiting for fix...", 0, 30)

        # 🌟GPS界面刷新后，更新/绘制电量
        self._update_battery()
        self.display.show()
        self.led_handler.toggle_mode_led()
        gc.collect()

    # GPS副界面：新增电量绘制
    def gps_second_display(self):
        self.display.fill(0)
        if self.gps.gps_data["utc_time"] and self.gps.gps_data["utc_date"] is not None:
            self.display.text("Timezone: UTC", 0, 0)
            self.display.text(f"Time: {self.gps.gps_data['utc_time']}", 0, 10)
            self.display.text(f"Date: {self.gps.gps_data['utc_date']}", 0, 20)

        if "sats" in self.gps.gps_data and self.gps.gps_data["sats"] is not None:
            self.display.text(f"Sats: {self.gps.gps_data['sats']}", 0, 30)

        if "pps" in self.gps.gps_data and self.gps.gps_data["pps"] is not None:
            self.display.text(f"PPS: {self.gps.gps_data['pps']}us", 0, 48)
        # 🌟副界面绘制后，更新/绘制电量
        self._update_battery()
        self.display.show()
        lightsleep(3000)
        gc.collect()

    # 距离模式：新增电量绘制
    def enter_distance_mode(self):
        if self.point_A is None:
            self.display_text("Distance Mode", "Set Point A", "Press SET")
        elif self.point_B is None:
            self.display_text("Point A set", "Set Point B", "Press SET")
        else:
            distance = haversine(
                self.point_A[0], self.point_A[1], self.point_B[0], self.point_B[1]
            )
            self.display_text("Distance:", f"{distance:.2f} m", "SET to reset")
        # 🌟距离模式绘制后，更新/绘制电量
        self._update_battery()
        self.display.show()
        gc.collect()

    # 设置界面：新增电量绘制（重写update_settings_display，最后更新电量）
    def update_settings_display(self):
        self.display.fill(0)
        self.display.text("Settings", 0, 0)

        start_index = max(0, self.settings_index - 1)
        end_index = min(len(self.SETTINGS_OPTIONS), start_index + 3)

        for i in range(start_index, end_index):
            option = self.SETTINGS_OPTIONS[i]
            prefix = ">" if i == self.settings_index else " "
            self.display.text(f"{prefix}{option}", 0, (i - start_index + 1) * 16)

        if self.settings_index == 0:
            value = f"Contrast: {self.settings_handler.get_setting('contrast', 'LCD_SETTINGS')}"
        elif self.settings_index == 1:
            value = f"Invert: {'On' if self.settings_handler.get_setting('invert', 'LCD_SETTINGS') else 'Off'}"
        elif self.settings_index == 2:
            value = f"PWR Save: {'On' if self.settings_handler.get_setting('pwr_save', 'DEVICE_SETTINGS') else 'Off'}"
        elif self.settings_index == 3:
            value = f"LEDs: {'On' if self.settings_handler.get_setting('enable_leds', 'DEVICE_SETTINGS') else 'Off'}"
        else:
            value = ""
        if value:
            self.display.text(value, 0, 56)
        # 🌟设置界面绘制后，更新/绘制电量
        self._update_battery()
        self.display.show()

    # 关于界面：新增电量绘制
    def display_about(self):
        self.display.fill(0)
        self.display.text("PocketBT 32 GPS", 0, 0)
        self.display.text("v1.1.2 By Easton & Yuki", 0, 9)
        cpu_freq = freq() / 1_000_000
        self.display.text(f"CPU: {cpu_freq:.0f} MHz", 0, 20)
        free_ram = gc.mem_free() / 1024
        self.display.text(f"RAM: {free_ram:.1f} KB", 0, 30)
        try:
            temp_fahrenheit = esp32.raw_temperature()
            temp_celsius = (temp_fahrenheit - 32) * 5 / 9
            self.display.text(f"Temp: {temp_celsius:.2f} C", 0, 40)
        except Exception as e:
            self.display.text("Temp info N/A", 0, 40)
            if self.DEBUG:
                print(f"[DEBUG] Error: {e}")
        self.display.text("Press NAV btn for more", 0, 50)
        # 🌟关于界面绘制后，更新/绘制电量
        self._update_battery()
        self.display.show()
        gc.collect()

    # 存储信息界面：新增电量绘制
    def display_device_storage(self):
        self.display.fill(0)
        self.display.text("Device Storage", 0, 0)
        try:
            storage_info = os.statvfs("/")
            total_space = storage_info[0] * storage_info[2] / (1024 * 1024)
            free_space = storage_info[0] * storage_info[3] / (1024 * 1024)
            flash_size = esp.flash_size()
            self.display.text(f"Storage: {free_space:.1f}/{total_space:.1f}MB", 0, 40)
            self.display.text(f"Flash: {flash_size}B", 0, 50)
        except Exception as e:
            self.display.text("Storage info N/A", 0, 40)
            if self.DEBUG:
                print(f"[DEBUG] Error: {e}")
        # 🌟存储界面绘制后，更新/绘制电量
        self._update_battery()
        self.display.show()
        utime.sleep(2.5)

    def set_distance_point(self):
        lat, lon = self.gps.gps_data["lat"], self.gps.gps_data["lon"]
        if self.gps.gps_data["fix"] == "Valid":
            if self.point_A is None:
                self.point_A = (lat, lon)
                self.display_text("Point A set", f"Lat: {lat:.6f}")
            elif self.point_B is None:
                self.point_B = (lat, lon)
                distance = haversine(
                    self.point_A[0], self.point_A[1], self.point_B[0], self.point_B[1]
                )
                self.display_text("Distance:", f"{distance:.2f} m", "Press mode btn")
            else:
                self.point_A = self.point_B = None
                self.display_text("Points reset", "Set new Point A")
            self.enter_distance_mode()
        else:
            self.display_text("No GPS fix", "Try again later")
            self.led_handler.set_error_led(1)
        gc.collect()

    def apply_setting_change(self):
        if self.settings_index == 0:
            current_contrast = self.settings_handler.get_setting("contrast", "LCD_SETTINGS")
            new_contrast = (current_contrast % 15) + 1
            self.settings_handler.update_setting("contrast", new_contrast, "LCD_SETTINGS")
            self.display.contrast(new_contrast)
        elif self.settings_index == 1:
            invert = self.settings_handler.get_setting("invert", "LCD_SETTINGS")
            self.settings_handler.update_setting("invert", not invert, "LCD_SETTINGS")
            self.display.invert(not invert)
        elif self.settings_index == 2:
            pwr_save = self.settings_handler.get_setting("pwr_save", "DEVICE_SETTINGS")
            self.settings_handler.update_setting("pwr_save", not pwr_save, "DEVICE_SETTINGS")
            freq(40000000 if not pwr_save else 160000000)
        elif self.settings_index == 3:
            enable_leds = self.settings_handler.get_setting("enable_leds", "DEVICE_SETTINGS")
            self.settings_handler.update_setting("enable_leds", not enable_leds, "DEVICE_SETTINGS")
        self.is_editing = not self.is_editing
        self.update_settings_display()
        gc.collect()

    # 通用文字显示方法：新增电量绘制
    def display_text(self, line1, line2=None, line3=None):
        self.display.fill(0)
        self.display.text(line1, 0, 0)
        if line2:
            self.display.text(line2, 0, 16)
        if line3:
            self.display.text(line3, 0, 24)
        # 🌟通用文字界面绘制后，更新/绘制电量
        self._update_battery()
        self.display.show()

    def toggle_display_power(self, timer=None):
        if self.DEBUG:
            print(f"[DEBUG] Toggling display power with timer: {timer}")
        if self.power_manager.state == "deep_sleep":
            utime.sleep_ms(500)
            self.power_manager.wake_from_deep_sleep()
            # 唤醒屏幕后立即更新电量
            self._update_battery()
            self.display.show()
        else:
            utime.sleep_ms(300)
            self.power_manager.enter_deep_sleep()

    def cycle_mode(self):
        if self.DEBUG:
            print(f"[DEBUG] cycle_mode called. Current mode: {self.current_mode}")
        self.current_mode = (self.current_mode + 1) % len(self.MODES)
        if self.DEBUG:
            print(f"[DEBUG] New mode after cycling: {self.current_mode}")

    def handle_nav_button(self):
        if self.current_mode == 0:
            self.show_second_gps_display()
        elif self.current_mode == 2:
            self.settings_index = (self.settings_index + 1) % len(self.SETTINGS_OPTIONS)
            self.update_settings_display()
        elif self.current_mode == 3:
            self.display_device_storage()
        else:
            self.display.fill(0)
            self._update_battery()
            self.display.show()

    def handle_set_button(self):
        if self.current_mode == 1:
            self.set_distance_point()
        elif self.current_mode == 2:
            self.apply_setting_change()
        if not self.current_mode == 0:
            self.update_settings_display()

    def initialize_builtin_led(self):
        builtin_led = Pin(2, Pin.OUT)
        builtin_led.value(0)
        return builtin_led
