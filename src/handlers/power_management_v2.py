from machine import Timer, lightsleep
import gc


class PowerManager:
    def __init__(self, display, gps, settings_handler, led_handler, display_handler, ble):
        # 注入所有外设/模块，新增ble实例用于频率控制
        self.display = display
        self.gps = gps
        self.settings_handler = settings_handler
        self.display_handler = display_handler
        self.led_handler = led_handler  # 预留扩展
        self.ble = ble  # 新增：BLEGPS实例，用于控制推送频率

        # 功耗状态：仅保留active/idle（浅睡）
        self.state = "active"
        
        # 基础超时配置（从配置读取，无则默认30秒）
        self.idle_timeout_ms = self.settings_handler.get_setting(
            "screen_timeout_ms", "DEVICE_SETTINGS", default=30000
        )
        
        # 空闲/活跃状态的频率配置（核心：GPS+BLE双降频）
        self.active_gps_interval = 1000  # 活跃：GPS1秒更新
        self.idle_gps_interval = 30000   # 空闲：GPS30秒更新
        self.active_ble_interval = 1000  # 活跃：BLE1秒推送
        self.idle_ble_interval = 30000   # 空闲：BLE30秒推送

        # 仅保留空闲超时定时器
        self.inactivity_timer = Timer(-1)

        # 初始化定时器
        self.init_timers()

    def init_timers(self):
        """初始化：重置空闲超时定时器"""
        self.reset_inactivity_timer()

    def reset_inactivity_timer(self):
        """重置空闲定时器（用户交互/状态恢复时调用）"""
        if self.inactivity_timer:
            self.inactivity_timer.deinit()
        print(f"[DEBUG] 重置空闲定时器 - 超时：{self.idle_timeout_ms}ms")
        self.inactivity_timer.init(
            period=self.idle_timeout_ms,
            mode=Timer.ONE_SHOT,
            callback=lambda t: self.enter_idle_mode()
        )

    def enter_idle_mode(self):
        """进入空闲（浅睡）模式：关屏+GPS降频+BLE降频+轻量休眠"""
        if self.state != "active":
            return
        print("[DEBUG] 进入空闲（浅睡）模式")
        self.state = "idle"

        # 1. 屏幕：显示提示后断电
        self.display.fill(0)
        self.display.text("Idle Mode", 20, 15, 1)
        self.display.text("BLE+GPS Low Freq", 0, 30, 1)
        self.display.show()
        lightsleep(1000)  # 1秒提示后关屏
        self.display.poweroff()

        # 2. GPS：降低更新频率
        self.gps.set_update_interval(self.idle_gps_interval)
        # 3. BLE：修改全局更新频率（核心：BLE降频）
        self.ble._UPDATE_INTERVAL = self.idle_ble_interval

        # 手动回收内存
        gc.collect()

    def exit_idle_mode(self):
        """退出空闲模式：亮屏+恢复GPS+恢复BLE频率"""
        print("[DEBUG] 退出空闲模式，恢复活跃")
        self.state = "active"

        # 1. 屏幕上电并恢复当前显示模式
        self.display.poweron()
        self.display_handler.enter_mode(self.display_handler.current_mode)

        # 2. GPS：恢复正常更新频率
        self.gps.set_update_interval(self.active_gps_interval)
        # 3. BLE：恢复正常推送频率
        self.ble._UPDATE_INTERVAL = self.active_ble_interval

        # 重置空闲定时器，销毁无用对象
        self.reset_inactivity_timer()
        gc.collect()

    def handle_user_interaction(self):
        """用户交互统一处理入口（按键/触屏均调用此方法）"""
        print(f"[DEBUG] 检测到用户交互，当前状态：{self.state}")
        if self.state == "idle":
            self.exit_idle_mode()  # 空闲→活跃
        else:
            self.reset_inactivity_timer()  # 活跃→刷新定时器

    def set_idle_timeout(self, timeout_ms):
        """外部修改空闲超时时间（可选扩展）"""
        self.idle_timeout_ms = max(timeout_ms, 5000)  # 最小5秒
        self.reset_inactivity_timer()

    def set_ble_gps_freq(self, active_ble, idle_ble, active_gps, idle_gps):
        """外部配置BLE/GPS的活跃/空闲频率（可选扩展）"""
        self.active_ble_interval = active_ble
        self.idle_ble_interval = idle_ble
        self.active_gps_interval = active_gps
        self.idle_gps_interval = idle_gps
        # 立即应用当前状态的频率
        if self.state == "active":
            self.gps.set_update_interval(active_gps)
            self.ble._UPDATE_INTERVAL = active_ble
        else:
            self.gps.set_update_interval(idle_gps)
            self.ble._UPDATE_INTERVAL = idle_ble
