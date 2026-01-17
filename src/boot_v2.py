# boot.py

from machine import (
    Pin,
    freq,
    ADC,
    lightsleep,
    reset_cause,
    DEEPSLEEP_RESET,
    RTC,
    Timer,
)

from handlers.gps_handler import GPSHandler
from handlers.settings_handler import SettingsHandler
from handlers.button_handler import ButtonHandler
from handlers.display_handler import DisplayHandler
from handlers.led_handler import LEDHandler
# [新增] 导入蓝牙NMEA处理器
from handlers.bt_nmea_handler import BtNMEAHandler


def initialize_handlers():
    settings_handler = SettingsHandler()
    led_handler = LEDHandler(settings_handler)
    gps = GPSHandler(led_handler)
    gps.init_gps()
    
    # [新增] 初始化蓝牙NMEA处理器
    bt_nmea_handler = BtNMEAHandler(gps, led_handler)
    
    # [新增] 初始化后立即打开蓝牙
    bt_nmea_handler.activate()
    
    display_handler = DisplayHandler(gps, led_handler, settings_handler)
    # [新增] 更新按钮处理器，传入蓝牙处理器
    button_handler = ButtonHandler(gps, display_handler, bt_nmea_handler)
    
    # [新增] 返回所有处理器，包括蓝牙处理器
    return settings_handler, led_handler, gps, display_handler, button_handler, bt_nmea_handler


def manage_boot_cycle():
    # Get boot cycle count from RTC memory
    rtc = RTC()
    boot_count = rtc.memory()
    if not boot_count:
        boot_count = 1
    else:
        boot_count = int(boot_count.decode()) + 1
    # Store the new boot count in RTC memory
    rtc.memory(str(boot_count).encode())
    print(f"[DEBUG] Boot cycle: {boot_count}")
    return boot_count


# Boot into power save mode instead of showing initial splash screen
# [新增] 添加蓝牙处理器参数
def enter_power_save_mode(settings_handler, display, bt_nmea_handler):
    if settings_handler.get_setting("pwr_save_boot", "DEVICE_SETTINGS"):
        # Set CPU frequency to 40MHz for power saving
        freq(40000000)
        # ADC power down
        adc = ADC(0)
        adc.atten(ADC.ATTN_11DB)
        adc.width(ADC.WIDTH_9BIT)
        display.poweroff()
        display.contrast(1)
        
        # [新增] 在省电模式下禁用蓝牙
        if bt_nmea_handler.is_active():
            bt_nmea_handler.deactivate()
            print("[POWER SAVE] Bluetooth disabled")
        
        # Delay turning on display upon boot for 5 seconds
        lightsleep(5000)
        display.poweron()
        
        # [新增] 省电模式结束后重新打开蓝牙
        bt_nmea_handler.activate()
        print("[POWER SAVE] Bluetooth reactivated after power save mode")


# Show boot screen only on the first boot, not on wake from deep sleep
def handle_boot_screen(display_handler):
    if reset_cause() != DEEPSLEEP_RESET:
        display_handler.display_boot_screen()


# [新增] 添加蓝牙处理器参数
def handle_deep_sleep(power_manager, bt_nmea_handler):
    if reset_cause() == DEEPSLEEP_RESET:
        power_manager.wake_from_deep_sleep()
        # [新增] 深度睡眠唤醒后重新打开蓝牙
        bt_nmea_handler.activate()
        print("[DEEP SLEEP] Bluetooth reactivated after wakeup")


# Built-in ESP32 LED
def initialize_builtin_led():
    builtin_led = Pin(2, Pin.OUT)
    builtin_led.value(0)
    return builtin_led


def setup_screen_timeout(settings_handler, power_manager):
    disp_timer = Timer(2)
    disp_timer.init(
        mode=Timer.ONE_SHOT,
        period=settings_handler.get_setting("screen_timeout_ms", "DEVICE_SETTINGS"),
        callback=lambda t: power_manager.enter_idle_mode(),
    )
    return disp_timer


def main():
    # [新增] 接收所有处理器，包括蓝牙处理器
    (
        settings_handler,
        led_handler,
        gps,
        display_handler,
        button_handler,
        bt_nmea_handler  # 蓝牙处理器
    ) = initialize_handlers()

    power_manager = display_handler.power_manager
    boot_count = manage_boot_cycle()
    
    # [新增] 传入蓝牙处理器
    enter_power_save_mode(settings_handler, display_handler, bt_nmea_handler)
    
    # [新增] 传入蓝牙处理器
    handle_deep_sleep(power_manager, bt_nmea_handler)

    handle_boot_screen(display_handler)
    builtin_led = initialize_builtin_led()
    disp_timer = setup_screen_timeout(settings_handler, power_manager)
    
    previous_mode = -1
    while True:
        try:
            # Only call enter_mode if the mode has changed
            if display_handler.current_mode != previous_mode:
                print(
                    f"[DEBUG] Mode changed: {previous_mode} -> {display_handler.current_mode}"
                )

                display_handler.enter_mode(display_handler.current_mode)
                previous_mode = display_handler.current_mode  # Update the tracked mode

            # GPS读取逻辑不变（仅模式0,1,2时读取）
            if display_handler.current_mode in [0, 1, 2]:  # Modes requiring GPS
                gps.read_gps()
            
            
            
            lightsleep(110)
        except Exception as e:
            print(f"Error: {e} ({type(e).__name__})")
            # [新增] 蓝牙错误处理
            if "bluetooth" in str(e).lower():
                bt_nmea_handler.deactivate()
                print("[BT ERROR] Bluetooth disabled due to error")
                # 稍后尝试重新打开蓝牙
                Timer().init(
                    mode=Timer.ONE_SHOT, 
                    period=5000, 
                    callback=lambda t: bt_nmea_handler.activate()
                )


if __name__ == "__main__":
    main()