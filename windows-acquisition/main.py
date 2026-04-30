"""
Fish Agent — 水听器单通道采集程序
用法:
  python main.py                          # 交互模式
  python main.py --duration 3600 --auto-upload   # 自动模式(采集1小时并上传)
  python main.py --duration 120 --output D:\\test.wav  # 指定输出路径
"""

import time
import ctypes
import wave
import struct
import sys
import argparse
import os
from ctypes import *
from datetime import datetime
from pathlib import Path

# ============================================================
# 加载配置文件 (如果存在)
# ============================================================
def load_config():
    cfg_path = Path(__file__).resolve().parent / "config.yaml"
    if cfg_path.exists():
        import yaml
        with open(cfg_path, encoding="utf-8") as f:
            return yaml.safe_load(f)
    return {}

cfg = load_config()
acq = cfg.get("acquisition", {})
out = cfg.get("output", {})
upload_cfg = cfg.get("upload", {})
realtime_cfg = cfg.get("realtime", {})

SAMPLE_RATE = acq.get("sample_rate", 100000)
COLLECT_CHANNEL = acq.get("channel", 0)
DEVICE_NO = 0
VOLT_RANGE = acq.get("volt_range", 2)
REFER_VOLT = acq.get("refer_volt", 4096)
IEPE_MODE = acq.get("iepe_mode", 0)
BUFFER_SIZE = acq.get("buffer_size", 1000)
WAVE_BIT_DEPTH = out.get("bit_depth", 16)
OUTPUT_DIR = out.get("directory", "D:\\fish_audio")
AUTO_UPLOAD_DEFAULT = upload_cfg.get("enabled", False)

# ============================================================
# 加载采集卡驱动 DLL
# ============================================================
brch = cdll.LoadLibrary(str(Path(__file__).resolve().parent / "BRC2.dll"))

DeviceOpen = brch.Device_Open
DeviceOpen.argtypes = []
DeviceOpen.restype = c_int

GetConnectedClientNumbers = brch.Device_Get_ConnectedClientNumbers
GetConnectedClientNumbers.argtypes = [POINTER(c_int)]
GetConnectedClientNumbers.restype = c_int

GetConnectedClientHandle = brch.Device_Get_ConnectedClientHandle
GetConnectedClientHandle.argtypes = [c_int, POINTER(c_int), POINTER(c_int), POINTER(c_char)]
GetConnectedClientHandle.restype = c_int

StartSampling = brch.VK70xUMC_StartSampling
StartSampling.argtypes = [c_int]
StartSampling.restype = c_int

StopSampling = brch.VK70xUMC_StopSampling
StopSampling.argtypes = [c_int]
StopSampling.restype = c_int

Initialize = brch.VK70xUMC_InitializeAll
Initialize.argtypes = [c_int, POINTER(c_int), c_int]
Initialize.restype = c_int

GetOneChannel = brch.VK70xUMC_GetOneChannel
GetOneChannel.argtypes = [c_int, c_int, POINTER(c_double), c_int]
GetOneChannel.restype = c_int

SetBlockingMethodtoReadADCResult = brch.VK70xUMC_Set_BlockingMethodtoReadADCResult
SetBlockingMethodtoReadADCResult.argtypes = [c_int, c_int]
SetBlockingMethodtoReadADCResult.restype = c_int

# ============================================================
def save_to_wav(data_list, sample_rate, file_path, bit_depth=16):
    n_channels = 1
    sampwidth = bit_depth // 8
    n_frames = len(data_list)
    max_volt = 2.5
    max_audio = 2 ** (bit_depth - 1) - 1
    normalized_data = [int(x / max_volt * max_audio) for x in data_list]

    with wave.open(file_path, "wb") as wf:
        wf.setparams((n_channels, sampwidth, sample_rate, n_frames, "NONE", "not compressed"))
        for val in normalized_data:
            wf.writeframes(struct.pack("<h", val))

    duration = len(data_list) / sample_rate
    print(f"\nWAV 文件保存成功: {file_path}")
    print(f"采样率: {sample_rate}Hz | 时长: {duration:.2f}s | 点数: {len(data_list)}")


def acquire_data(duration_sec):
    """采集指定时长的数据，返回电压数据列表"""
    total_need_points = int(SAMPLE_RATE * duration_sec)
    collect_data = []

    # 1. 打开设备
    result = DeviceOpen()
    if result < 0:
        raise RuntimeError("打开设备端口失败")

    # 2. 查找采集卡
    curDeviceNum = c_int(0)
    while GetConnectedClientNumbers(byref(curDeviceNum)) < 0:
        time.sleep(0.001)
    if curDeviceNum.value == 0:
        raise RuntimeError("未检测到采集卡")

    # 3. 初始化参数
    paraInitialize = (c_int32 * 20)()
    for i in range(20):
        paraInitialize[i] = 0
    paraInitialize[0] = 0x22
    paraInitialize[1] = SAMPLE_RATE
    paraInitialize[3] = REFER_VOLT
    paraInitialize[4] = VOLT_RANGE
    paraInitialize[12] = IEPE_MODE

    if Initialize(DEVICE_NO, paraInitialize, 20) < 0:
        raise RuntimeError("初始化参数失败")

    # 4. 设置阻塞模式
    if SetBlockingMethodtoReadADCResult(1, 1000) < 0:
        raise RuntimeError("配置读取模式失败")

    # 5. 启动采样
    if StartSampling(DEVICE_NO) < 0:
        raise RuntimeError("启动采样失败")

    print(f"采样中... {duration_sec}s | 通道CH{COLLECT_CHANNEL+1} | {SAMPLE_RATE}Hz")

    try:
        data_buffer = (c_double * BUFFER_SIZE)()
        total_collect = 0
        while total_collect < total_need_points:
            recv = GetOneChannel(DEVICE_NO, COLLECT_CHANNEL, data_buffer, BUFFER_SIZE)
            if recv > 0:
                collect_data.extend([data_buffer[i] for i in range(recv)])
                total_collect += recv
                pct = total_collect / total_need_points * 100
                print(f"进度: {pct:.1f}% | {total_collect}/{total_need_points}", end="\r")
    finally:
        StopSampling(DEVICE_NO)

    print(f"\n采集完成! 共 {len(collect_data)} 点")
    return collect_data


def try_upload(filepath):
    """尝试上传文件到服务器"""
    try:
        from uploader import upload_file, load_config
        cfg = load_config()
        server_url = cfg["upload"]["server_url"]
        retry_max = cfg["upload"].get("retry_max", 3)
        retry_delay = cfg["upload"].get("retry_delay_sec", 5)
        upload_file(filepath, server_url, retry_max, retry_delay)
    except ImportError:
        print("缺少依赖，跳过上传 (pip install requests pyyaml)")
    except Exception as e:
        print(f"上传失败: {e}")


def get_output_path(custom_path=None):
    """生成输出文件路径"""
    if custom_path:
        return custom_path
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return os.path.join(OUTPUT_DIR, f"fish_{ts}.wav")


def run_realtime_mode(args):
    import threading
    from realtime_uploader import RealtimeQueue, RealtimeUploadClient, create_session

    server_url = upload_cfg["server_url"]
    chunk_duration = realtime_cfg.get("chunk_duration_sec", 2.0)
    session_id = args.session_id
    if session_id is None:
        session = create_session(server_url, args.client_id, args.session_name, chunk_duration)
        session_id = session["id"]
        print(f"实时会话已创建: {session_id}")

    queue = RealtimeQueue(args.queue_dir)
    uploader = RealtimeUploadClient(server_url, queue)
    stop_event = threading.Event()
    sequence = queue.max_sequence(session_id) + 1

    def upload_worker():
        while not stop_event.is_set():
            try:
                pending_items = queue.pending_items()
            except Exception as e:
                print(f"读取实时上传队列失败: {e}")
                time.sleep(2)
                continue

            for item in pending_items:
                try:
                    uploader.upload_item(item)
                except Exception as e:
                    print(f"上传分片失败: {item.meta_path} | {e}")
            try:
                uploader.send_heartbeat(session_id, args.client_id)
            except Exception as e:
                print(f"heartbeat 失败: {e}")
            time.sleep(2)

    print(f"实时监测启动 | session={session_id} | client={args.client_id}")
    worker = threading.Thread(target=upload_worker, daemon=True)
    worker.start()
    try:
        while True:
            captured_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            output_path = get_output_path()
            data = acquire_data(chunk_duration)
            save_to_wav(data, SAMPLE_RATE, output_path, WAVE_BIT_DEPTH)
            wav_bytes = Path(output_path).read_bytes()
            queue.enqueue(session_id, args.client_id, sequence, captured_at, SAMPLE_RATE, chunk_duration, wav_bytes)
            try:
                Path(output_path).unlink()
            except OSError as e:
                print(f"清理实时临时文件失败: {e}")
            print(f"实时分片 {sequence} 已入队 | 待上传: {len(queue.pending_items())}")
            sequence += 1
    except KeyboardInterrupt:
        stop_event.set()
        worker.join(timeout=5)
        print("实时监测已停止")


def run_agent_mode(args):
    from realtime_agent import RealtimeAgent
    from realtime_uploader import RealtimeQueue, RealtimeUploadClient

    server_url = upload_cfg["server_url"]
    chunk_duration = realtime_cfg.get("chunk_duration_sec", 2.0)
    queue = RealtimeQueue(args.queue_dir)
    uploader = RealtimeUploadClient(server_url, queue)

    def capture_chunk(duration):
        output_path = get_output_path()
        data = acquire_data(duration)
        save_to_wav(data, SAMPLE_RATE, output_path, WAVE_BIT_DEPTH)
        wav_bytes = Path(output_path).read_bytes()
        try:
            Path(output_path).unlink()
        except OSError as e:
            print(f"清理实时临时文件失败: {e}")
        return wav_bytes

    agent = RealtimeAgent(
        client_id=args.client_id,
        name=args.session_name,
        queue=queue,
        uploader=uploader,
        capture_chunk=capture_chunk,
        sample_rate=SAMPLE_RATE,
        chunk_duration=chunk_duration,
    )

    print(f"实时采集代理启动 | client={args.client_id} | server={server_url}")
    print("请在前端实时监测页面选择该 client_id 后开始或停止采集")
    try:
        while True:
            try:
                agent.run_once()
            except Exception as e:
                print(f"实时采集代理循环失败: {e}")
                agent.status = "error"
                agent.message = str(e)
            time.sleep(args.agent_poll_interval)
    except KeyboardInterrupt:
        print("实时采集代理已停止")


# ============================================================
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fish Agent 水听器采集")
    parser.add_argument("--duration", "-d", type=float, help="采集时长(秒)")
    parser.add_argument("--output", "-o", help="输出 WAV 文件路径")
    parser.add_argument("--auto-upload", action="store_true", default=AUTO_UPLOAD_DEFAULT,
                        help="采集完成后自动上传到服务器")
    parser.add_argument("--no-upload", action="store_true", help="禁用自动上传")
    parser.add_argument("--realtime", action="store_true", default=realtime_cfg.get("enabled", False),
                        help="启用实时分片上传模式")
    parser.add_argument("--agent", action="store_true", default=realtime_cfg.get("agent_enabled", False),
                        help="启用前端控制的常驻实时采集代理")
    parser.add_argument("--session-id", type=int, help="已有实时会话 ID")
    parser.add_argument("--session-name", default=realtime_cfg.get("session_name", "pond-a"),
                        help="实时会话名称")
    parser.add_argument("--client-id", default=realtime_cfg.get("client_id", "pond-a-windows-01"),
                        help="采集客户端 ID")
    parser.add_argument("--queue-dir", default=realtime_cfg.get("queue_dir", "D:\\fish_audio\\realtime_queue"),
                        help="实时上传队列目录")
    parser.add_argument("--agent-poll-interval", type=float,
                        default=realtime_cfg.get("agent_poll_interval_sec", 2.0),
                        help="实时采集代理轮询服务器命令的间隔(秒)")
    args = parser.parse_args()

    do_upload = args.auto_upload and not args.no_upload

    if args.agent:
        run_agent_mode(args)
        sys.exit(0)

    if args.realtime:
        run_realtime_mode(args)
        sys.exit(0)

    # 获取采集时长
    if args.duration:
        collect_time = args.duration
        print(f"采集时长(命令行指定): {collect_time}s")
    else:
        while True:
            try:
                collect_time = float(input("请输入采集时长(秒): "))
                if collect_time > 0:
                    break
                print("时长必须大于0")
            except ValueError:
                print("请输入数字")

    output_path = get_output_path(args.output)
    print(f"输出文件: {output_path}")

    # 非交互模式不需要按回车
    if not args.duration:
        input("按下回车键开始采集...")

    try:
        data = acquire_data(collect_time)
        if data:
            save_to_wav(data, SAMPLE_RATE, output_path, WAVE_BIT_DEPTH)

            if do_upload:
                print("\n--- 上传文件 ---")
                try_upload(output_path)
        else:
            print("未采集到有效数据")
    except RuntimeError as e:
        print(f"错误: {e}")
        sys.exit(1)

    print("\n===== 程序结束 =====")
