package com.fishfeed.entity;

import lombok.Data;
//实时监测结果实体类

@Data
public class MonitorResult {
    private String status;         // 监测状态：监测中/已暂停
    private String currentType;    // 当前识别：鱼类摄食声/背景噪音
    private Double confidence;     // 置信度
    private Integer totalCount;    // 累计摄食次数
    private String intensity;      // 摄食强度：高/中/低
    private String suggestion;     // 智能投喂建议
    private String decisionAction; // 策略动作：WAIT/FEED_START/FEED_HOLD/FEED_REDUCE/FEED_STOP
    private Double fishRatio;      // 当前分片鱼声占比
    private Double windowFishRatio; // 决策窗口鱼声占比
    private String sourceMode;     // 数据来源模式
    private String lastChunkAt;    // 最近分片时间
    private String lastChunkName;  // 最近分片文件名
    private String lastDeviceId;   // 最近上传设备标识
}
