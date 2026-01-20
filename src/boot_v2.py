# boot.py

from machine import (
    Pin,
    freq,
    ADC,
    lightsleep,
    RTC,
    Timer,
)

# 移除深睡相关的DEEPSLEEP_RESET导入（冲突核心1）
from handlers.gps_handler import GPSHandler
from handlers.settings_handler import SettingsHandler
from handlers.button_handler import ButtonHandler
from handlers.display_handler import DisplayHandler
from handlers.led_handler import LEDHandler
from handlers.bt_nmea_handler import BtNMEAHandler


def initialize_handlers():
    settings_handler = SettingsHandler()
    led_handler = LEDHandler(settings_handler)
    gps = GPSHandler(led_handler)
    gps.init_gps()

    # 初始化蓝牙NMEA处理器
    bt_nmea_handler = BtNMEAHandler(gps, led_handler)
    # 初始化后立即打开蓝牙
    bt_nmea_handler.activate()

    display_handler = DisplayHandler(gps, led_handler, settings_handler)
    # 更新按钮处理器，传入蓝牙处理器
    button_handler = ButtonHandler(gps, display_handler, bt_nmea_handler)

    return settings_handler, led_handler, gps, display_handler, button_handler, bt_nmea_handler


def manage_boot_cycle():
    # RTC内存记录启动次数，保留原逻辑
    rtc = RTC()
    boot_count = rtc.memory()
    if not boot_count:
        boot_count = 1
    else:
        boot_count = int(boot_count.decode()) + 1
    rtc.memory(str(boot_count).encode())
    print(f"[DEBUG] Boot cycle: {boot_count}")
    return boot_count


# 省电模式：保留蓝牙临时关闭/恢复逻辑，无冲突
def enter_power_save_mode(settings_handler, display, bt_nmea_handler):
    if settings_handler.get_setting("pwr_save_boot", "DEVICE_SETTINGS"):
        # 降频+ADC省电
        freq(40000000)
        adc = ADC(0)
        adc.atten(ADC.ATTN_11DB)
        adc.width(ADC.WIDTH_9BIT)
        display.poweroff()
        display.contrast(1)

        # 省电模式禁用蓝牙
        if bt_nmea_handler.is_active():
            bt_nmea_handler.deactivate()
            print("[POWER SAVE] Bluetooth disabled")

        # 5秒浅睡后开屏
        lightsleep(5000)
        display.poweron()

        # 省电结束恢复蓝牙
        bt_nmea_handler.activate()
        print("[POWER SAVE] Bluetooth reactivated after power save mode")


# 开机画面：仅首次启动显示，移除深睡唤醒判断（冲突核心2）
def handle_boot_screen(display_handler):
    # 原逻辑是深睡唤醒不显示开机屏，现在无深睡，直接显示开机屏即可
    display_handler.display_boot_screen()


# 初始化板载LED，保留原逻辑
def initialize_builtin_led():
    builtin_led = Pin(2, Pin.OUT)
    builtin_led.value(0)
    return builtin_led


# 屏幕超时定时器：适配浅睡版PowerManager的空闲模式
def setup_screen_timeout(settings_handler, power_manager):
    disp_timer = Timer(2)
    disp_timer.init(
        mode=Timer.ONE_SHOT,
        period=settings_handler.get_setting("screen_timeout_ms", "DEVICE_SETTINGS"),
        callback=lambda t: power_manager.enter_idle_mode(),
    )
    return disp_timer


def main():
    # 初始化所有处理器（含蓝牙）
    (
        settings_handler,
        led_handler,
        gps,
        display_handler,
        button_handler,
        bt_nmea_handler
    ) = initialize_handlers()

    # 绑定浅睡版PowerManager（无深睡逻辑）
    power_manager = display_handler.power_manager
    boot_count = manage_boot_cycle()

    # 执行开机省电模式（含蓝牙控制）
    enter_power_save_mode(settings_handler, display_handler, bt_nmea_handler)

    # 显示开机画面（已移除深睡判断）
    handle_boot_screen(display_handler)
    builtin_led = initialize_builtin_led()
    disp_timer = setup_screen_timeout(settings_handler, power_manager)

    previous_mode = -1
    while True:
        try:
            # 屏显模式切换刷新，保留原逻辑
            if display_handler.current_mode != previous_mode:
                print(
                    f"[DEBUG] Mode changed: {previous_mode} -> {display_handler.current_mode}"
                )
                display_handler.enter_mode(display_handler.current_mode)
                previous_mode = display_handler.current_mode

            # 仅定位模式读取GPS数据，保留原逻辑
            if display_handler.current_mode in [0, 1, 2]:
                gps.read_gps()

            # 轻量休眠，降低CPU占用，保留原逻辑
            lightsleep(110)

        except Exception as e:
            print(f"Error: {e} ({type(e).__name__})")
            # 蓝牙异常处理：补全原代码未写完的逻辑，避免语法报错
            if "bluetooth" in str(e).lower():
                bt_nmea_handler.deactivate()
                print("[BT ERROR] Bluetooth disabled due to error")
                # 5秒后自动尝试重新激活蓝牙，增加异常恢复
                Timer().init(
                    mode=Timer.ONE_SHOT,
                    period=5000,
                    callback=lambda t: bt_nmea_handler.activate()
                )


# 程序入口，规范写法
if __name__ == "__main__":
    main()