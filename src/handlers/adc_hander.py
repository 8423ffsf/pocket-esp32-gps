# adc_handler.py - ESP32全系列通用
# 核心适配：ADC_MULTIPLIER = (R1+R2)/R2 分压系数公式
# 配置：1.1V内部参考+0dB衰减+12位采样+抗蓝牙/GPS干扰
from machine import ADC, Pin
import math

class ADCHandler:
    def __init__(self, adc_pin=0, atten=ADC.ATTN_0DB, width=ADC.WIDTH_12BIT, adc_multiplier=1.0):
        """
        ESP32全系列通用ADC初始化，适配ADC_MULTIPLIER分压公式
        :param adc_pin: ADC引脚（C3=0/2/4；原版ESP32=0~18）
        :param atten: 衰减值，固定0dB（全系列量程0~1.1V，1.1V通用参考）
        :param width: 采样位宽，固定12位（0~4095，最高精度）
        :param adc_multiplier: 分压系数=(R1+R2)/R2，R1=上拉(接电池)，R2=下拉(接地)，无分压=1.0
        """
        self.adc = ADC(Pin(adc_pin))
        self.adc.atten(atten)
        self.adc.width(width)
        
        # 抗干扰配置（蓝牙/GPS高频杂波过滤）
        self.sample_times = 20
        self.sample_delay = 0
        
        # 核心参数
        self.calib_coeff = 1.0  # 硬件校准系数（修正ADC采样微小偏差，默认1.0）
        self.REF_VOLTAGE = 1.1  # ESP32全系列通用1.1V内部参考电压
        self.MAX_RAW_VALUE = 4095  # 12位采样最大原始值
        self.adc_multiplier = adc_multiplier  # 你指定的分压系数(R1+R2)/R2

    def set_calib_coeff(self, coeff):
        """设置硬件校准系数，修正ADC采样偏差（建议0.9~1.1之间）"""
        if 0.8 <= coeff <= 1.2:
            self.calib_coeff = coeff

    def set_adc_multiplier(self, multiplier):
        """单独修改分压系数，更换电阻后直接调用，无需重新初始化"""
        if multiplier >= 1.0:  # 分压系数最小为1.0（无分压）
            self.adc_multiplier = multiplier

    def _get_raw_average(self):
        """内部方法：多次采样取平均，滤除蓝牙/GPS高频干扰"""
        raw_sum = 0
        for _ in range(self.sample_times):
            raw_sum += self.adc.read()
            if self.sample_delay > 0:
                import utime
                utime.sleep_us(self.sample_delay)
        return raw_sum // self.sample_times

    def get_adc_voltage(self):
        """获取ADC引脚的原始采集电压（未分压/未校准，调试硬件用）"""
        raw_avg = self._get_raw_average()
        adc_v = (raw_avg / self.MAX_RAW_VALUE) * self.REF_VOLTAGE
        return round(adc_v, 3)

    def get_voltage(self):
        """
        核心方法：获取电池真实电压（按你指定公式计算）
        公式：真实电压 = ADC原始采集电压 × ADC_MULTIPLIER × 硬件校准系数
        """
        adc_v = self.get_adc_voltage()
        real_v = adc_v * self.adc_multiplier * self.calib_coeff
        return round(real_v, 2)  # 保留2位小数，贴合电池电压显示

    def get_battery_percent(self, min_v=3.0, max_v=4.2):
        """
        计算锂电池剩余百分比（通用3.0V低电~4.2V满电，可按需修改）
        :param min_v: 电池放电截止电压，低于此值为0%
        :param max_v: 电池满电电压，高于此值为100%
        """
        current_v = self.get_voltage()
        if current_v >= max_v:
            return 100
        elif current_v <= min_v:
            return 0
        percent = (current_v - min_v) / (max_v - min_v) * 100
        return math.ceil(percent)

    def deinit(self):
        """释放ADC资源，低功耗场景使用"""
        self.adc.deinit()

# 测试代码（示例：R1=22k，R2=10k → adc_multiplier=(22+10)/10=3.2）
if __name__ == "__main__":
    import utime
    # 初始化：指定引脚+分压系数(ADC_MULTIPLIER)
    adc_handler = ADCHandler(adc_pin=0, adc_multiplier=3.2)
    # 可选：设置校准系数（按实测值计算后填入，例：1.01）
    adc_handler.set_calib_coeff(1.01)
    while True:
        adc_v = adc_handler.get_adc_voltage()  # ADC引脚原始电压（调试）
        real_v = adc_handler.get_voltage()      # 电池真实电压（实际使用）
        pct = adc_handler.get_battery_percent() # 剩余电量
        print(f"ADC采集：{adc_v}V | 电池电压：{real_v}V | 剩余电量：{pct}%")
        utime.sleep(1)
