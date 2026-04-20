package com.fishfeed.config;

import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.List;

@Data
@Component
@ConfigurationProperties(prefix = "fishfeed.logging")
public class LoggingConfigProperties {
    private boolean requestTraceEnabled = true;
    private long slowRequestMs = 800;
    private List<String> tracePathPrefixes = new ArrayList<>(List.of(
            "/realtime",
            "/upload-audio",
            "/analyze-audio"
    ));
}
