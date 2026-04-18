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
}
