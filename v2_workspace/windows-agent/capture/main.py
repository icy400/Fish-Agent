import time
import ctypes
import wave
import struct
from ctypes import*

# 加载采集卡驱动DLL文件
brch = cdll.LoadLibrary('./BRC2.dll')

# 打开设备端口
DeviceOpen = brch.Device_Open
DeviceOpen.argtypes = []
DeviceOpen.restype = c_int

# 读取已连接的采集卡数量
GetConnectedClientNumbers = brch.Device_Get_ConnectedClientNumbers
GetConnectedClientNumbers.argtypes = [POINTER(c_int)]
GetConnectedClientNumbers.restype = c_int

# 读取采集卡句柄、型号、序列号(IP地址)
GetConnectedClientHandle = brch.Device_Get_ConnectedClientHandle
GetConnectedClientHandle.argtypes = [c_int, POINTER(c_int), POINTER(c_int), POINTER(c_char)]
GetConnectedClientHandle.restype = c_int

# 启动连续采样
StartSampling = brch.VK70xUMC_StartSampling
StartSampling.argtypes = [c_int]
StartSampling.restype = c_int

# 停止采样
StopSampling = brch.VK70xUMC_StopSampling
StopSampling.argtypes = [c_int]
StopSampling.restype = c_int

# 初始化采集卡核心参数【采样率/量程/参考电压都在这里配置】
Initialize = brch.VK70xUMC_InitializeAll
Initialize.argtypes = [c_int, POINTER(c_int), c_int]
Initialize.restype = c_int

# 切换系统采样模式
SetSystemMode = brch.VK70xUMC_Set_SampleMode
SetSystemMode.argtypes = [c_int, c_int]
SetSystemMode.restype = c_int

# 纯读【单通道】数据 
GetOneChannel = brch.VK70xUMC_GetOneChannel
GetOneChannel.argtypes = [c_int, c_int, POINTER(c_double), c_int]
GetOneChannel.restype = c_int

# 设置阻塞读取模式
SetBlockingMethodtoReadADCResult = brch.VK70xUMC_Set_BlockingMethodtoReadADCResult
SetBlockingMethodtoReadADCResult.argtypes = [c_int, c_int]
SetBlockingMethodtoReadADCResult.restype = c_int

# ----------------------------------------------------------------------------------------

# ----------------------------------------------------------------------------------------
SAMPLE_RATE = 100000          # 采样率：100000Hz
COLLECT_CHANNEL = 0          # 采集通道：0=CH1，1=CH2，2=CH3，3=CH4，按需改即可
DEVICE_NO = 0                # 采集卡序号，单卡固定0
VOLT_RANGE = 2               # CH1电压量程：=±2.5V
REFER_VOLT = 4096            # 参考电压
IEPE_MODE = 0                # 普通ADC采样模式，固定0

# WAV文件配置
WAVE_FILE_PATH = r"D:\ceshi.wav"  #固定保存到盘根目录
WAVE_BIT_DEPTH = 16               

# 初始化变量
curDeviceNum = c_int(0)
curHandle = c_int(0)
vkType = c_int(0)
serialNum = ctypes.create_string_buffer(128)  
paraInitialize = (ctypes.c_int32 * 20)()      


# ----------------------------------------------------------------------------------------
def save_to_wav(data_list, sample_rate, file_path, bit_depth=16):
    """
    将采集的电压数据保存为标准WAV文件
    :param data_list: 采集的单通道电压数据列表
    :param sample_rate: 采样率
    :param file_path: 保存路径
    :param bit_depth: 位深 16/32
    """
    # WAV文件参数配置
    n_channels = 1        # 单声道（对应单通道采集）
    sampwidth = bit_depth // 8
    n_frames = len(data_list)
    comptype = "NONE"
    compname = "not compressed"
    

    max_volt = 2.5
    max_audio = 2 ** (bit_depth - 1) - 1
    normalized_data = [int(x / max_volt * max_audio) for x in data_list]
    
    # 创建并写入WAV文件
    with wave.open(file_path, 'wb') as wf:
        wf.setparams((n_channels, sampwidth, sample_rate, n_frames, comptype, compname))
        # 将归一化的数据打包为二进制流写入
        for val in normalized_data:
            wf.writeframes(struct.pack('<h', val))
    print(f"\ WAV文件保存成功！路径：{file_path}")
    print(f"采样率：{sample_rate}Hz | 采集时长：{len(data_list)/sample_rate:.2f}s | 总采样点数：{len(data_list)}")


# ----------------------------------------------------------------------------------------
if __name__ == "__main__":
    print("===== 单通道采集程序【100000Hz采样率 → 保存D盘ceshi.wav】 =====")
    collect_data = []  # 存储所有采集的电压数据，全程不丢失
    flag_run = True

    # 1. 打开设备端口
    print("\n打开设备端口...")
    result = DeviceOpen()
    if(result < 0):
        print("打开设备端口失败，程序退出")
        flag_run = False
    else:
        print("打开设备端口成功")

    # 2. 获取已连接的采集卡数量
    if flag_run:
        print("查找已连接的采集卡...")
        result = -1
        while result < 0:
            result = GetConnectedClientNumbers(byref(curDeviceNum))
            time.sleep(0.001)
        print(f"查找成功，当前连接采集卡数量：{curDeviceNum.value}")
        if curDeviceNum.value == 0:
            print("❌ 无采集卡连接，程序退出")
            flag_run = False


  

    # 5. 初始化核心参数 - 固定100000Hz采样率+单通道配置
    if flag_run:
        print("初始化采集卡参数 - 采样率固定100000Hz...")
        for i in range(20): paraInitialize[i] = 0
        paraInitialize[0]  = 0x22        # 固定启动采样命令
        paraInitialize[1]  = SAMPLE_RATE # 写入100000Hz采样率
        paraInitialize[3]  = REFER_VOLT  # 参考电压
        paraInitialize[4]  = VOLT_RANGE  # CH1量程
        paraInitialize[12] = IEPE_MODE   
        result = Initialize(DEVICE_NO, paraInitialize, 20)
        if (result < 0): print("❌ 初始化参数失败"); flag_run = False
        else: print("初始化成功，采样率锁定：{}Hz".format(SAMPLE_RATE))

    # 6. 设置阻塞读取模式
    if flag_run:
        print("配置数据读取模式...")
        result = SetBlockingMethodtoReadADCResult(1, 1000)
        if (result < 0): print("❌ 配置读取模式失败"); flag_run = False
        else: print("配置阻塞读取模式成功，超时1000ms")

    # 7. 手动输入采集时长 + 开始采集核心逻辑
    if flag_run:
        print("\n=====================================")
        # 手动输入采集时长，单位：秒，支持小数（比如 2.5 = 2.5秒）
        while True:
            try:
                collect_time = float(input(f"请输入需要采集的时长（单位：秒）："))
                if collect_time > 0: break
                else: print("❌ 时长必须大于0，请重新输入！")
            except:
                print("❌ 输入格式错误，请输入数字（如：1、2.5、5）！")
        
        # 计算需要采集的总点数 = 采样率 × 采集时长
        total_need_points = int(SAMPLE_RATE * collect_time)
        print(f"\n 采集配置确认：单通道CH{COLLECT_CHANNEL+1} | 100000Hz | 时长{collect_time}s | 总点数{total_need_points}")
        input("按下回车键，开始采集数据...")

        # 启动连续采样
        print("\n启动采样...")
        result = StartSampling(DEVICE_NO)
        if (result < 0):
            print("❌ 启动采样失败")
        else:
            print("采样启动成功！正在采集数据，请稍候...")
            # 初始化单通道数据缓冲区，每次读取1000点，高效采集
            buffer_size = 1000
            data_buffer = (ctypes.c_double * buffer_size)()
            recv_len = 0
            total_collect = 0

            # 循环采集，直到采集满指定点数
            while total_collect < total_need_points and flag_run:
                recv_len = GetOneChannel(DEVICE_NO, COLLECT_CHANNEL, data_buffer, buffer_size)
                if recv_len > 0:
                    # 将读取到的ctypes数组转成python列表，存入总数据列表
                    collect_data.extend([data_buffer[i] for i in range(recv_len)])
                    total_collect += recv_len
                    # 打印进度
                    progress = (total_collect / total_need_points) * 100
                    print(f"采集进度：{progress:.1f}% | 已采点数：{total_collect}/{total_need_points}", end="\r")
            
            # 采集完成，必须停止采样！保护硬件
            StopSampling(DEVICE_NO)
            print("\n采集完成！已停止采样")

            # 将采集的数据保存为WAV文件到I盘
            if len(collect_data) > 0:
                save_to_wav(collect_data, SAMPLE_RATE, WAVE_FILE_PATH)
            else:
                print("❌ 未采集到有效数据，未生成WAV文件")

print("\n===== 程序运行结束 =====")