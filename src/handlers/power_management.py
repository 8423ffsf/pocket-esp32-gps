# src/handlers/power_management.py


from machine import Timer, deepsleep, lightsleep
import gc
import esp32


class PowerManager:
    def __init__(self, display, gps, settings_handler, led_handler, display_handler, ble=None):
        self.display = display
        self.gps = gps
        self.settings_handler = settings_handler
        self.display_handler = display_handler
        self.led_handler = led_handler  # Not used
        self.ble = ble  # 新增：注入BLE实例，默认为None（兼容原代码调用）

        self.state = "active"
        self.idle_timeout_ms = self.settings_handler.get_setting(
            "screen_timeout_ms", "DEVICE_SETTINGS"
        )
        self.deepsleep_timeout_ms = 480000  # 8 minutes
        self.inactivity_timer = Timer(-1)
        self.prolonged_inactivity_timer = Timer(-1)

        # Wake from deep sleep button
        self.display_power_button = None

        self.init_timers()

    def init_timers(self):
        self.reset_inactivity_timer()

    # Used for idle mode
    def reset_inactivity_timer(self):
        if self.inactivity_timer:
            self.inactivity_timer.deinit()
        print(f"[DEBUG] Resetting inactivity timer. Timeout: {self.idle_timeout_ms} ms")
        self.inactivity_timer.init(
            period=self.idle_timeout_ms,
            mode=Timer.ONE_SHOT,
            callback=lambda t: self.enter_idle_mode(),
        )

    # Used for deep sleep mode
    def reset_prolonged_inactivity_timer(self):
        if self.prolonged_inactivity_timer:
            self.prolonged_inactivity_timer.deinit()
        print(
            f"[DEBUG] Resetting prolonged inactivity timer. Timeout: {self.deepsleep_timeout_ms} ms"
        )
        self.prolonged_inactivity_timer.init(
            period=self.deepsleep_timeout_ms,
            mode=Timer.ONE_SHOT,
            callback=lambda t: self.enter_deep_sleep(),
        )

    def enter_idle_mode(self):
        if self.state != "active":
            return
        print("[DEBUG] Entering Idle Mode")
        self.state = "idle"

        self.display.fill(0)
        self.display.fill_rect(0, 0, 128, 48, 0)
        self.display.text("Entering", 0, 0)
        self.display.text(f" {self.state} mode....", 0, 10)
        self.display.show()
        lightsleep(1500)

        self.display.poweroff()
        self.gps.set_update_interval(30000)  # 30 seconds
        self.reset_prolonged_inactivity_timer()

        gc.collect()

    def exit_idle_mode(self):
        print("[DEBUG] Exiting Idle Mode")
        self.state = "active"
        self.display.poweron()
        self.gps.set_update_interval(1000)  # 1 second
        self.reset_inactivity_timer()
        if self.prolonged_inactivity_timer:
            print("Deinit prolonged inactivity timer")
            self.prolonged_inactivity_timer.deinit()
        gc.collect()

        # This is to ensure the device is in the correct mode when waking up
        self.display_handler.enter_mode(self.display_handler.current_mode)

    def enter_deep_sleep(self):
        print("[DEBUG] Entering deep sleep mode")
        self.state = "deep_sleep"
        self.display.poweroff()
        self.gps.power_off()
        # 新增：深睡时关闭BLE，先判断实例是否存在，避免报错
        if self.ble and hasattr(self.ble, '_ble'):
            self.ble._ble.active(False)  # 关闭BLE射频，彻底停止BLE工作
            print("[DEBUG] BLE deactivated for deep sleep")
        # 原深睡唤醒配置不变
        esp32.wake_on_ext0(pin=self.display_power_button, level=0)
        deepsleep()

    def wake_from_deep_sleep(self):
        print("[DEBUG] Waking from deep sleep mode")
        self.state = "active"
        self.display.poweron()
        self.gps.power_on()
        # 新增：深睡唤醒后重新初始化BLE，恢复原工作状态
        if self.ble and hasattr(self.ble, '_ble'):
            self.ble._ble.active(True)  # 重新激活BLE射频
            self.ble._ble.gap_advertise(30000, adv_data=self.ble._adv_payload)  # 恢复广播
            print("[DEBUG] BLE reactivated and advertising resumed")
        self.reset_inactivity_timer()
        gc.collect()

    def handle_user_interaction(self):
        print(f"[DEBUG] User interaction detected. Current state: {self.state}")
        if self.state == "idle":
            self.exit_idle_mode()
        elif self.state == "deep_sleep":
            self.wake_from_deep_sleep()
        else:
            self.reset_inactivity_timer()

    # Set the display power button pin used for deep sleep
    def set_display_power_button(self, button):
        print(
            f"[DEBUG] Idle timeout: {self.idle_timeout_ms} ms, Deep sleep timeout: {self.deepsleep_timeout_ms} ms"
        )
        self.display_power_button = button