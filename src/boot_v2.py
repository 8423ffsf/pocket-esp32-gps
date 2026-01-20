# boot.py

from machine import (
    Pin,
    freq,
    ADC,
    lightsleep,
    RTC,
    Timer,
)

# 彻底移除深睡相关导入，无DEEPSLEEP_RESET
from handlers.gps_handler import GPSHandler
from handlers.settings_handler import SettingsHandler
from handlers.button_handler import ButtonHandler
from handlers.display_handler import DisplayHandler
from handlers.led_handler import LEDHandler
from handlers.bt_nmea_handler import BtNMEAHandler


def initialize_handlers():
    """初始化所有处理器，蓝牙开机自动激活（核心：不关闭，仅后续浅睡降频）"""
    settings_handler = SettingsHandler()
    led_handler = LEDHandler(settings_handler)
    gps = GPSHandler(led_handler)
    gps.init_gps()

    # 初始化蓝牙NMEA处理器，绑定GPS和LED
    bt_nmea_handler = BtNMEAHandler(gps, led_handler)
    # 开机立即激活蓝牙，后续仅PowerManager浅睡时降频率，不关闭
    bt_nmea_handler.activate()
    print("[BT INIT] 蓝牙已开机激活，浅睡将仅降低推送频率")

    display_handler = DisplayHandler(gps, led_handler, settings_handler)
    # 按键处理器传入蓝牙，支持按键控制（如需）
    button_handler = ButtonHandler(gps, display_handler, bt_nmea_handler)

    return settings_handler, led_handler, gps, display_handler, button_handler, bt_nmea_handler


def manage_boot_cycle():
    """RTC记录启动次数，保留原逻辑"""
    rtc = RTC()
    boot_count = rtc.memory()
    boot_count = 1 if not boot_count else int(boot_count.decode()) + 1
    rtc.memory(str(boot_count).encode())
    print(f"[DEBUG] 启动次数: {boot_count}")
    return boot_count


def enter_power_save_mode(settings_handler, display, bt_nmea_handler):
    """开机省电模式：仅开机阶段临时关闭蓝牙5秒（非浅睡），5秒后自动恢复"""
    if settings_handler.get_setting("pwr_save_boot", "DEVICE_SETTINGS"):
        # CPU降频+ADC省电+屏幕关闭，开机功耗优化
        freq(40000000)
        adc = ADC(0)
        adc.atten(ADC.ATTN_11DB)
        adc.width(ADC.WIDTH_9BIT)
        display.poweroff()
        display.contrast(1)

        # 开机省电：临时关闭蓝牙（仅5秒，非浅睡逻辑）
        if bt_nmea_handler.is_active():
            bt_nmea_handler.deactivate()
            print("[POWER SAVE] 开机省电模式：蓝牙临时关闭5秒")

        # 5秒轻量休眠后开屏，恢复正常工作
        lightsleep(5000)
        display.poweron()

        # 开机省电结束，重新激活蓝牙（恢复正常频率，非降频）
        bt_nmea_handler.activate()
        print("[POWER SAVE] 开机省电模式结束，蓝牙已恢复激活（正常频率）")


def handle_boot_screen(display_handler):
    """显示开机画面：无深睡，所有启动均显示"""
    display_handler.display_boot_screen()


def initialize_builtin_led():
    """初始化板载LED，保留原逻辑"""
    builtin_led = Pin(2, Pin.OUT)
    builtin_led.value(0)
    return builtin_led


def setup_screen_timeout(settings_handler, power_manager):
    """屏幕超时定时器：触发PowerManager浅睡（仅降频，不关闭蓝牙），核心适配"""
    disp_timer = Timer(2)
    disp_timer.init(
        mode=Timer.ONE_SHOT,
        period=settings_handler.get_setting("screen_timeout_ms", "DEVICE_SETTINGS"),
        callback=lambda t: power_manager.enter_idle_mode(),  # 触发浅睡降频
    )
    return disp_timer


def main():
    # 初始化所有处理器（蓝牙已开机激活）
    (
        settings_handler,
        led_handler,
        gps,
        display_handler,
        button_handler,
        bt_nmea_handler
    ) = initialize_handlers()

    # 绑定【移除深睡+浅睡降BLE频率】的PowerManager实例
    power_manager = display_handler.power_manager
    manage_boot_cycle()

    # 执行开机省电（仅开机5秒临时关蓝牙，与浅睡无关）
    enter_power_save_mode(settings_handler, display_handler, bt_nmea_handler)

    # 显示开机画面
    handle_boot_screen(display_handler)
    initialize_builtin_led()
    setup_screen_timeout(settings_handler, power_manager)  # 绑定屏超时触发浅睡

    previous_mode = -1
    while True:
        try:
            # 屏显模式切换刷新，保留原逻辑
            if display_handler.current_mode != previous_mode:
                print(f"[DEBUG] 模式切换: {previous_mode} -> {display_handler.current_mode}")
                display_handler.enter_mode(display_handler.current_mode)
                previous_mode = display_handler.current_mode

            # 仅定位模式读取GPS数据，蓝牙随GPS更新推送（频率由PowerManager控制）
            if display_handler.current_mode in [0, 1, 2]:
                gps.read_gps()

            # 全局轻量休眠，降低CPU占用，与PowerManager无冲突
            lightsleep(110)

        except Exception as e:
            print(f"[ERROR] 异常: {e} ({type(e).__name__})")
            # 蓝牙异常处理：仅异常时关闭，5秒后自动恢复激活（非浅睡逻辑）
            if "bluetooth" in str(e).lower():
                bt_nmea_handler.deactivate()
                print("[BT ERROR] 蓝牙检测到异常，临时关闭")
                # 5秒后自动尝试重新激活蓝牙，恢复正常工作
                Timer().init(
                    mode=Timer.ONE_SHOT,
                    period=5000,
                    callback=lambda t: bt_nmea_handler.activate()
                )


# 程序规范入口
if __name__ == "__main__":
    main()