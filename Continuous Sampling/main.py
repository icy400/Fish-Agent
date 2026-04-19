import time
import ctypes
import wave
import struct
import uuid
import datetime as dt
import logging
import shutil
from logging.handlers import RotatingFileHandler
from pathlib import Path
from ctypes import *

try:
    import requests
except ImportError:
    requests = None

# ========================= 日志配置 =========================
LOG_ENABLED = True
LOG_FILE_PATH = Path("collector_runtime.log")
LOG_MAX_BYTES = 5 * 1024 * 1024
LOG_BACKUP_COUNT = 3

logger = logging.getLogger("hydrophone_collector")
if LOG_ENABLED and not logger.handlers:
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler = RotatingFileHandler(
        LOG_FILE_PATH,
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)


def log_info(message: str):
    print(message)
    if LOG_ENABLED:
        logger.info(message)


def log_error(message: str):
    print(message)
    if LOG_ENABLED:
        logger.error(message)


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
SAMPLE_RATE = 100000
COLLECT_CHANNEL = 0
DEVICE_NO = 0
VOLT_RANGE = 2
REFER_VOLT = 4096
IEPE_MODE = 0

# WAV文件配置
WAVE_FILE_PATH = r"D:\ceshi.wav"
WAVE_BIT_DEPTH = 16
SAVE_LOCAL_WAV = True

# C方案：磁盘保护阈值（GB）
ENABLE_DISK_GUARD = True
DISK_WARN_GB = 2.0      # 低于该值：自动关闭本地WAV保存
DISK_CRITICAL_GB = 1.0  # 低于该值：仅保留实时上传能力并给出告警
DISK_STOP_GB = 0.5      # 低于该值：停止采集，保护系统
DISK_CHECK_INTERVAL_SECONDS = 3

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


def get_monitor_disk_path() -> Path:
    wave_drive = Path(WAVE_FILE_PATH).drive
    if wave_drive:
        return Path(f"{wave_drive}\\")
    return Path.cwd()


def get_free_disk_gb(target_path: Path) -> float:
    usage = shutil.disk_usage(str(target_path))
    return usage.free / (1024 ** 3)


def evaluate_disk_policy(save_local_wav_active: bool, disk_path: Path):
    """
    返回: (continue_run, save_local_wav_active)
    """
    if not ENABLE_DISK_GUARD:
        return True, save_local_wav_active

    free_gb = get_free_disk_gb(disk_path)

    if free_gb < DISK_STOP_GB:
        log_error(f"❌ 磁盘剩余 {free_gb:.2f}GB < {DISK_STOP_GB}GB，触发保护停机")
        return False, False

    if free_gb < DISK_CRITICAL_GB:
        log_error(f"⚠️ 磁盘紧急：剩余 {free_gb:.2f}GB < {DISK_CRITICAL_GB}GB，仅保留上传")
        return True, False

    if free_gb < DISK_WARN_GB and save_local_wav_active:
        log_info(f"⚠️ 磁盘预警：剩余 {free_gb:.2f}GB < {DISK_WARN_GB}GB，自动关闭本地WAV保存")
        return True, False

    return True, save_local_wav_active


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
        log_error("⚠️ requests未安装，无法上传。请先 pip install requests")
        return

    chunk_id = str(uuid.uuid4())
    timestamp_utc = dt.datetime.utcnow().isoformat() + "Z"

    try:
        wav_bytes = build_wav_bytes(chunk_data, sample_rate, bit_depth=WAVE_BIT_DEPTH)
        files = {"file": (f"{chunk_id}.wav", wav_bytes, "audio/wav")}
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
                log_info(f"[上传成功] class={result.get('predicted_class')} conf={result.get('confidence')}")
            else:
                log_error(f"[上传返回失败] {payload}")
        else:
            log_error(f"[上传失败] HTTP {response.status_code} {response.text}")
    except Exception as exc:
        log_error(f"[上传异常] {exc}")


def save_to_wav(data_list, sample_rate, file_path, bit_depth=16):
    """将采集的电压数据保存为标准WAV文件"""
    n_channels = 1
    sampwidth = bit_depth // 8
    n_frames = len(data_list)
    comptype = "NONE"
    compname = "not compressed"

    max_volt = 2.5
    max_audio = 2 ** (bit_depth - 1) - 1
    normalized_data = [int(max(-max_audio - 1, min(max_audio, x / max_volt * max_audio))) for x in data_list]

    with wave.open(file_path, 'wb') as wf:
        wf.setparams((n_channels, sampwidth, sample_rate, n_frames, comptype, compname))
        for val in normalized_data:
            wf.writeframes(struct.pack('<h', int(val)))

    log_info(f"WAV文件保存成功！路径：{file_path}")
    log_info(f"采样率：{sample_rate}Hz | 采集时长：{len(data_list)/sample_rate:.2f}s | 总采样点数：{len(data_list)}")


if __name__ == "__main__":
    log_info("===== 单通道采集程序【100000Hz采样率】 =====")
    collect_data = []
    upload_buffer = []
    flag_run = True
    save_local_wav_active = SAVE_LOCAL_WAV
    monitor_disk_path = get_monitor_disk_path()
    last_disk_check_ts = 0.0

    log_info(f"磁盘监控路径：{monitor_disk_path}")
    if LOG_ENABLED:
        log_info(f"运行日志文件：{LOG_FILE_PATH.resolve()}")

    # 1. 打开设备端口
    log_info("打开设备端口...")
    result = DeviceOpen()
    if result < 0:
        log_error("打开设备端口失败，程序退出")
        flag_run = False
    else:
        log_info("打开设备端口成功")

    # 2. 获取已连接的采集卡数量
    if flag_run:
        log_info("查找已连接的采集卡...")
        result = -1
        while result < 0:
            result = GetConnectedClientNumbers(byref(curDeviceNum))
            time.sleep(0.001)
        log_info(f"查找成功，当前连接采集卡数量：{curDeviceNum.value}")
        if curDeviceNum.value == 0:
            log_error("❌ 无采集卡连接，程序退出")
            flag_run = False

    # 5. 初始化核心参数
    if flag_run:
        log_info("初始化采集卡参数 - 采样率固定100000Hz...")
        for i in range(20):
            paraInitialize[i] = 0
        paraInitialize[0] = 0x22
        paraInitialize[1] = SAMPLE_RATE
        paraInitialize[3] = REFER_VOLT
        paraInitialize[4] = VOLT_RANGE
        paraInitialize[12] = IEPE_MODE
        result = Initialize(DEVICE_NO, paraInitialize, 20)
        if result < 0:
            log_error("❌ 初始化参数失败")
            flag_run = False
        else:
            log_info(f"初始化成功，采样率锁定：{SAMPLE_RATE}Hz")

    # 6. 设置阻塞读取模式
    if flag_run:
        log_info("配置数据读取模式...")
        result = SetBlockingMethodtoReadADCResult(1, 1000)
        if result < 0:
            log_error("❌ 配置读取模式失败")
            flag_run = False
        else:
            log_info("配置阻塞读取模式成功，超时1000ms")

    # 7. 采样流程
    if flag_run:
        while True:
            try:
                collect_time = float(input("请输入需要采集的时长（单位：秒）："))
                if collect_time > 0:
                    break
                log_error("❌ 时长必须大于0，请重新输入！")
            except Exception:
                log_error("❌ 输入格式错误，请输入数字（如：1、2.5、5）！")

        total_need_points = int(SAMPLE_RATE * collect_time)
        log_info(
            f"采集配置：CH{COLLECT_CHANNEL+1} | {SAMPLE_RATE}Hz | 时长{collect_time}s | 总点数{total_need_points}"
        )
        log_info(
            f"实时上传：{'开启' if UPLOAD_ENABLED else '关闭'} | URL={UPLOAD_URL if UPLOAD_ENABLED else '-'} | 分片={CHUNK_SECONDS}s"
        )
        log_info(f"本地WAV保存：{'开启' if save_local_wav_active else '关闭'} | 目标={WAVE_FILE_PATH}")
        input("按下回车键，开始采集数据...")

        result = StartSampling(DEVICE_NO)
        if result < 0:
            log_error("❌ 启动采样失败")
        else:
            log_info("采样启动成功！正在采集数据，请稍候...")
            buffer_size = 1000
            chunk_points = max(1, int(SAMPLE_RATE * CHUNK_SECONDS))
            data_buffer = (ctypes.c_double * buffer_size)()
            total_collect = 0

            while total_collect < total_need_points and flag_run:
                now = time.time()
                if now - last_disk_check_ts >= DISK_CHECK_INTERVAL_SECONDS:
                    last_disk_check_ts = now
                    continue_run, save_local_wav_active = evaluate_disk_policy(
                        save_local_wav_active, monitor_disk_path
                    )
                    if not continue_run:
                        flag_run = False
                        break

                recv_len = GetOneChannel(DEVICE_NO, COLLECT_CHANNEL, data_buffer, buffer_size)
                if recv_len > 0:
                    current = [data_buffer[i] for i in range(recv_len)]
                    upload_buffer.extend(current)
                    if save_local_wav_active:
                        collect_data.extend(current)

                    total_collect += recv_len

                    while len(upload_buffer) >= chunk_points:
                        chunk = upload_buffer[:chunk_points]
                        del upload_buffer[:chunk_points]
                        upload_chunk_to_linux(chunk, SAMPLE_RATE, COLLECT_CHANNEL)

                    progress = (total_collect / total_need_points) * 100
                    print(f"采集进度：{progress:.1f}% | 已采点数：{total_collect}/{total_need_points}", end="\r")

            StopSampling(DEVICE_NO)
            print("\n", end="")
            log_info("采集结束，已停止采样")

            if upload_buffer:
                upload_chunk_to_linux(upload_buffer, SAMPLE_RATE, COLLECT_CHANNEL)

            if save_local_wav_active and len(collect_data) > 0:
                save_to_wav(collect_data, SAMPLE_RATE, WAVE_FILE_PATH)
            elif not save_local_wav_active:
                log_info("本次采集未保存本地WAV（磁盘保护策略触发或配置关闭）")
            else:
                log_error("❌ 未采集到有效数据，未生成WAV文件")

log_info("===== 程序运行结束 =====")
