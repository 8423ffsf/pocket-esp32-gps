# adc_handler.py - ESP32全系列通用
# 新增：原生支持分压比配置，自动还原电池真实电压
# 配置：1.1V内部参考+0dB衰减+12位采样+抗蓝牙/GPS干扰
from machine import ADC, Pin
import math

class ADCHandler:
    def __init__(self, adc_pin=0, atten=ADC.ATTN_0DB, width=ADC.WIDTH_12BIT, div_ratio=1.0):
        """
        ESP32全系列通用ADC初始化，支持分压比配置
        :param adc_pin: ADC引脚（C3=0/2/4；原版ESP32=0~18）
        :param atten: 衰减值，固定0dB（全系列量程0~1.1V）
        :param width: 采样位宽，固定12位（0~4095）
        :param div_ratio: 分压比，默认1.0（无分压直接接电池时用，分压则填计算值）
        """
        self.adc = ADC(Pin(adc_pin))
        self.adc.atten(atten)
        self.adc.width(width)
        
        # 抗干扰配置
        self.sample_times = 20
        self.sample_delay = 0
        
        # 核心参数
        self.calib_coeff = 1.0  # 硬件校准系数（修正采样偏差）
        self.REF_VOLTAGE = 1.1  # ESP32全系列通用1.1V内部参考
        self.MAX_RAW_VALUE = 4095
        self.div_ratio = div_ratio  # 新增：分压比（硬件决定）

    def set_calib_coeff(self, coeff):
        """设置最终校准系数（分压比+硬件偏差，按公式计算后填入）"""
        if 0.5 <= coeff <= 2.0:  # 放宽范围，适配分压场景
            self.calib_coeff = coeff

    def set_div_ratio(self, ratio):
        """单独修改分压比（若后期更换分压电阻，无需重新初始化）"""
        if 0.01 <= ratio <= 1.0:
            self.div_ratio = ratio

    def _get_raw_average(self):
        """多次采样取平均，滤除无线干扰"""
        raw_sum = 0
        for _ in range(self.sample_times):
            raw_sum += self.adc.read()
            if self.sample_delay > 0:
                import utime
                utime.sleep_us(self.sample_delay)
        return raw_sum // self.sample_times

    def get_adc_voltage(self):
        """获取ADC引脚的采集电压（分压后电压，调试用）"""
        raw_avg = self._get_raw_average()
        adc_v = (raw_avg / self.MAX_RAW_VALUE) * self.REF_VOLTAGE
        return round(adc_v, 3)

    def get_voltage(self):
        """
        核心：获取电池真实电压（自动还原分压，最终对外使用的方法）
        公式：真实电压 = ADC采集电压 × 最终校准系数 ÷ 分压比
        """
        adc_v = self.get_adc_voltage()
        real_v = adc_v * self.calib_coeff / self.div_ratio
        return round(real_v, 2)  # 保留2位小数，贴合电池电压显示习惯

    def get_battery_percent(self, min_v=3.0, max_v=4.2):
        """
        计算电池剩余百分比（适配锂电池3.0~4.2V通用阈值，可按需修改）
        :param min_v: 电池低电压阈值（锂电池放电截止≈3.0V）
        :param max_v: 电池满电电压阈值（锂电池满电≈4.2V）
        :return: 0~100整数百分比
        """
        current_v = self.get_voltage()
        if current_v >= max_v:
            return 100
        elif current_v <= min_v:
            return 0
        percent = (current_v - min_v) / (max_v - min_v) * 100
        return math.ceil(percent)

    def deinit(self):
        """释放ADC资源"""
        self.adc.deinit()

# 测试代码（分压场景示例：R上22k，R下10k，分压比0.3125）
if __name__ == "__main__":
    import utime
    # 初始化：指定adc_pin + 分压比
    adc_handler = ADCHandler(adc_pin=0, div_ratio=0.3125)
    # 设置最终校准系数（按公式计算后填入，例：1.101）
    adc_handler.set_calib_coeff(1.101)
    while True:
        adc_v = adc_handler.get_adc_voltage()  # 分压后电压（调试）
        real_v = adc_handler.get_voltage()      # 电池真实电压（使用）
        p = adc_handler.get_battery_percent()   # 剩余电量
        print(f"ADC采集电压：{adc_v}V | 电池真实电压：{real_v}V | 电量：{p}%")
        utime.sleep(1)
