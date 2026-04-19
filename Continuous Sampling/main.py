import time
import ctypes
import wave
import struct
import uuid
import datetime as dt
from ctypes import *

try:
    import requests
except ImportError:
    requests = None

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
SAMPLE_RATE = 100000          # 采样率：100000Hz
COLLECT_CHANNEL = 0           # 采集通道：0=CH1，1=CH2，2=CH3，3=CH4，按需改即可
DEVICE_NO = 0                 # 采集卡序号，单卡固定0
VOLT_RANGE = 2                # CH1电压量程：=±2.5V
REFER_VOLT = 4096             # 参考电压
IEPE_MODE = 0                 # 普通ADC采样模式，固定0

# WAV文件配置
WAVE_FILE_PATH = r"D:\ceshi.wav"  # 固定保存到盘根目录
WAVE_BIT_DEPTH = 16

# Linux分析服务配置
UPLOAD_ENABLED = True
UPLOAD_URL = "http://127.0.0.1:8000/api/v1/analyze"
DEVICE_ID = "windows-hydrophone-1"
CHUNK_SECONDS = 1.0
REQUEST_TIMEOUT_SECONDS = 8

# 初始化变量
curDeviceNum = c_int(0)
curHandle = c_int(0)
vkType = c_int(0)
serialNum = ctypes.create_string_buffer(128)
paraInitialize = (ctypes.c_int32 * 20)()


def to_pcm16_bytes(data_list, bit_depth=16):
    """将电压值转为PCM16字节流。"""
    max_volt = 2.5
    max_audio = 2 ** (bit_depth - 1) - 1
    pcm_data = bytearray()
    for x in data_list:
        scaled = int(x / max_volt * max_audio)
        if scaled > max_audio:
            scaled = max_audio
        elif scaled < -max_audio - 1:
            scaled = -max_audio - 1
        pcm_data.extend(struct.pack('<h', scaled))
    return bytes(pcm_data)


def build_wav_bytes(data_list, sample_rate, bit_depth=16):
    """把采样点构造成内存中的WAV字节。"""
    pcm_bytes = to_pcm16_bytes(data_list, bit_depth=bit_depth)
    n_channels = 1
    sampwidth = bit_depth // 8
    n_frames = len(data_list)
    header = wave._wave_params((n_channels, sampwidth, sample_rate, n_frames, 'NONE', 'not compressed'))

    import io
    bio = io.BytesIO()
    with wave.open(bio, 'wb') as wf:
        wf.setparams(header)
        wf.writeframes(pcm_bytes)
    return bio.getvalue()


def upload_chunk_to_linux(chunk_data, sample_rate, channel):
    """上传单个音频片段到Linux分析服务。"""
    if not UPLOAD_ENABLED:
        return
    if requests is None:
        print("⚠️ requests未安装，无法上传。请先 pip install requests")
        return

    chunk_id = str(uuid.uuid4())
    timestamp_utc = dt.datetime.utcnow().isoformat() + "Z"

    try:
        wav_bytes = build_wav_bytes(chunk_data, sample_rate, bit_depth=WAVE_BIT_DEPTH)
        files = {
            "file": (f"{chunk_id}.wav", wav_bytes, "audio/wav")
        }
        data = {
            "device_id": DEVICE_ID,
            "chunk_id": chunk_id,
            "timestamp_utc": timestamp_utc,
            "sample_rate": sample_rate,
            "channel": channel,
        }
        response = requests.post(
            UPLOAD_URL,
            files=files,
            data=data,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        if response.ok:
            payload = response.json()
            if payload.get("ok"):
                result = payload.get("result", {})
                print(
                    f"\n[上传成功] class={result.get('predicted_class')} conf={result.get('confidence')}"
                )
            else:
                print(f"\n[上传返回失败] {payload}")
        else:
            print(f"\n[上传失败] HTTP {response.status_code} {response.text}")
    except Exception as exc:
        print(f"\n[上传异常] {exc}")


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
    normalized_data = [int(max(-max_audio - 1, min(max_audio, x / max_volt * max_audio))) for x in data_list]

    # 创建并写入WAV文件
    with wave.open(file_path, 'wb') as wf:
        wf.setparams((n_channels, sampwidth, sample_rate, n_frames, comptype, compname))
        # 将归一化的数据打包为二进制流写入
        for val in normalized_data:
            wf.writeframes(struct.pack('<h', int(val)))
    print(f"\\ WAV文件保存成功！路径：{file_path}")
    print(f"采样率：{sample_rate}Hz | 采集时长：{len(data_list)/sample_rate:.2f}s | 总采样点数：{len(data_list)}")


# ----------------------------------------------------------------------------------------
if __name__ == "__main__":
    print("===== 单通道采集程序【100000Hz采样率】 =====")
    collect_data = []  # 存储所有采集的电压数据，全程不丢失
    upload_buffer = []
    flag_run = True

    # 1. 打开设备端口
    print("\n打开设备端口...")
    result = DeviceOpen()
    if result < 0:
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
        for i in range(20):
            paraInitialize[i] = 0
        paraInitialize[0] = 0x22        # 固定启动采样命令
        paraInitialize[1] = SAMPLE_RATE # 写入100000Hz采样率
        paraInitialize[3] = REFER_VOLT  # 参考电压
        paraInitialize[4] = VOLT_RANGE  # CH1量程
        paraInitialize[12] = IEPE_MODE
        result = Initialize(DEVICE_NO, paraInitialize, 20)
        if result < 0:
            print("❌ 初始化参数失败")
            flag_run = False
        else:
            print("初始化成功，采样率锁定：{}Hz".format(SAMPLE_RATE))

    # 6. 设置阻塞读取模式
    if flag_run:
        print("配置数据读取模式...")
        result = SetBlockingMethodtoReadADCResult(1, 1000)
        if result < 0:
            print("❌ 配置读取模式失败")
            flag_run = False
        else:
            print("配置阻塞读取模式成功，超时1000ms")

    # 7. 手动输入采集时长 + 开始采集核心逻辑
    if flag_run:
        print("\n=====================================")
        while True:
            try:
                collect_time = float(input("请输入需要采集的时长（单位：秒）："))
                if collect_time > 0:
                    break
                print("❌ 时长必须大于0，请重新输入！")
            except Exception:
                print("❌ 输入格式错误，请输入数字（如：1、2.5、5）！")

        total_need_points = int(SAMPLE_RATE * collect_time)
        print(
            f"\n采集配置确认：单通道CH{COLLECT_CHANNEL+1} | 100000Hz | 时长{collect_time}s | 总点数{total_need_points}"
        )
        print(
            f"实时上传：{'开启' if UPLOAD_ENABLED else '关闭'} | URL={UPLOAD_URL if UPLOAD_ENABLED else '-'} | 分片={CHUNK_SECONDS}s"
        )
        input("按下回车键，开始采集数据...")

        print("\n启动采样...")
        result = StartSampling(DEVICE_NO)
        if result < 0:
            print("❌ 启动采样失败")
        else:
            print("采样启动成功！正在采集数据，请稍候...")
            buffer_size = 1000
            chunk_points = max(1, int(SAMPLE_RATE * CHUNK_SECONDS))
            data_buffer = (ctypes.c_double * buffer_size)()
            total_collect = 0

            while total_collect < total_need_points and flag_run:
                recv_len = GetOneChannel(DEVICE_NO, COLLECT_CHANNEL, data_buffer, buffer_size)
                if recv_len > 0:
                    current = [data_buffer[i] for i in range(recv_len)]
                    collect_data.extend(current)
                    upload_buffer.extend(current)
                    total_collect += recv_len

                    while len(upload_buffer) >= chunk_points:
                        chunk = upload_buffer[:chunk_points]
                        del upload_buffer[:chunk_points]
                        upload_chunk_to_linux(chunk, SAMPLE_RATE, COLLECT_CHANNEL)

                    progress = (total_collect / total_need_points) * 100
                    print(f"采集进度：{progress:.1f}% | 已采点数：{total_collect}/{total_need_points}", end="\r")

            StopSampling(DEVICE_NO)
            print("\n采集完成！已停止采样")

            if upload_buffer:
                upload_chunk_to_linux(upload_buffer, SAMPLE_RATE, COLLECT_CHANNEL)

            if len(collect_data) > 0:
                save_to_wav(collect_data, SAMPLE_RATE, WAVE_FILE_PATH)
            else:
                print("❌ 未采集到有效数据，未生成WAV文件")

print("\n===== 程序运行结束 =====")
