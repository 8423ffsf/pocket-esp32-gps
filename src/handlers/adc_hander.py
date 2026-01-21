# adc_handler.py - ESP32全系列通用
# 配置：1.1V内部参考电压(全系列通用) + 0dB衰减 + 12位采样 + 抗蓝牙/GPS干扰
from machine import ADC, Pin
import math

class ADCHandler:
    def __init__(self, adc_pin=0, atten=ADC.ATTN_0DB, width=ADC.WIDTH_12BIT):
        """
        ESP32全系列通用ADC初始化，基于1.1V内部参考电压
        :param adc_pin: ADC引脚，按实际型号映射（例：C3=0/2/4；原版ESP32=0~18）
        :param atten: 衰减值，固定0dB（全系列量程0~1.1V，1.1V通用参考）
        :param width: 采样位宽，固定12位（全系列0~4095，最高精度）
        """
        # 初始化ADC，ESP32全系列machine.ADC接口通用
        self.adc = ADC(Pin(adc_pin))
        self.adc.atten(atten)  # 0dB衰减，无放大，全系列通用配置
        self.adc.width(width)  # 12位采样，全系列通用配置
        
        # 抗干扰配置（适配蓝牙/GPS高频杂波，便携设备专用）
        self.sample_times = 20  # 多次采样平均，滤除无线干扰
        self.sample_delay = 0  # 采样间隔，微秒级，平衡精度和速度
        
        # ESP32全系列通用核心参数
        self.calib_coeff = 1.0  # 硬件校准系数（修正分压/线路/引脚偏差）
        self.REF_VOLTAGE = 1.1  # 🌟ESP32全系列通用1.1V内部参考电压
        self.MAX_RAW_VALUE = 4095  # 12位采样最大原始值，全系列通用

    def set_calib_coeff(self, coeff):
        """设置校准系数，全系列通用，例：实测1.0V显示0.97V → 设1.03"""
        if 0.8 <= coeff <= 1.2:  # 限制系数范围，避免校准过度
            self.calib_coeff = coeff

    def _get_raw_average(self):
        """内部方法：多次采样取平均，抗蓝牙/GPS干扰，全系列通用"""
        raw_sum = 0
        for _ in range(self.sample_times):
            raw_sum += self.adc.read()
            if self.sample_delay > 0:
                import utime
                utime.sleep_us(self.sample_delay)
        return raw_sum // self.sample_times

    def get_voltage(self):
        """
        计算实际采集电压(V)，ESP32全系列通用公式
        公式：实际电压 = (原始平均值/最大原始值) × 1.1V × 校准系数
        """
        raw_avg = self._get_raw_average()
        voltage = (raw_avg / self.MAX_RAW_VALUE) * self.REF_VOLTAGE * self.calib_coeff
        return round(voltage, 3)  # 保留3位小数，兼顾精度和显示

    def get_battery_percent(self, min_v=0.8, max_v=1.1):
        """
        计算电池剩余百分比(0~100)，适配0dB+1.1V参考的采集区间
        :param min_v: 低电压阈值(建议≥0.8V，避免电池过放)
        :param max_v: 满电电压阈值(1.1V=0dB采样上限，全系列通用)
        :return: 整数百分比，超出范围返回0/100
        """
        current_v = self.get_voltage()
        if current_v >= max_v:
            return 100
        elif current_v <= min_v:
            return 0
        # 线性计算剩余电量，全系列通用逻辑
        percent = (current_v - min_v) / (max_v - min_v) * 100
        return math.ceil(percent)

    def deinit(self):
        """释放ADC资源，低功耗场景使用，ESP32全系列通用"""
        self.adc.deinit()

# 测试代码（单独运行，ESP32全系列通用）
if __name__ == "__main__":
    import utime
    # 初始化：按自己的ESP32型号改adc_pin即可，其余全通用
    adc_handler = ADCHandler(adc_pin=0)  # C3用0/2/4；原版ESP32可任意ADC引脚
    # 若有硬件偏差，校准：adc_handler.set_calib_coeff(1.02)
    while True:
        v = adc_handler.get_voltage()
        p = adc_handler.get_battery_percent()
        print(f"采集电压：{v}V | 剩余电量：{p}%")
        utime.sleep(1)
