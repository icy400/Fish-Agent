package com.fishfeed.config;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;
import java.util.List;
import java.util.concurrent.atomic.AtomicLong;

@Component
public class RequestTraceFilter extends OncePerRequestFilter {
    
    private static final Logger log = LoggerFactory.getLogger(RequestTraceFilter.class);
    private static final AtomicLong REQUEST_SEQ = new AtomicLong(0);
    
    @Autowired
    private LoggingConfigProperties loggingConfig;
    
    @Override
    protected boolean shouldNotFilter(HttpServletRequest request) {
        if (!loggingConfig.isRequestTraceEnabled()) {
            return true;
        }
        String uri = request.getRequestURI();
        List<String> prefixes = loggingConfig.getTracePathPrefixes();
        if (prefixes == null || prefixes.isEmpty()) {
            return false;
        }
        for (String prefix : prefixes) {
            if (uri.startsWith(prefix)) {
                return false;
            }
        }
        return true;
    }
    
    @Override
    protected void doFilterInternal(
            HttpServletRequest request,
            HttpServletResponse response,
            FilterChain filterChain
    ) throws ServletException, IOException {
        long reqId = REQUEST_SEQ.incrementAndGet();
        long start = System.currentTimeMillis();
        String method = request.getMethod();
        String uri = request.getRequestURI();
        String query = request.getQueryString();
        String pathWithQuery = query == null ? uri : uri + "?" + query;
        String remote = request.getRemoteAddr();
        
        try {
            filterChain.doFilter(request, response);
        } catch (ServletException | IOException | RuntimeException ex) {
            long cost = System.currentTimeMillis() - start;
            log.error(
                    "[req-{}] {} {} from={} status={} costMs={} error={}",
                    reqId, method, pathWithQuery, remote, response.getStatus(), cost, ex.toString(), ex
            );
            throw ex;
        } finally {
            long cost = System.currentTimeMillis() - start;
            int status = response.getStatus();
            if (cost >= loggingConfig.getSlowRequestMs()) {
                log.warn(
                        "[req-{}] {} {} from={} status={} costMs={} (slow)",
                        reqId, method, pathWithQuery, remote, status, cost
                );
            } else {
                log.info(
                        "[req-{}] {} {} from={} status={} costMs={}",
                        reqId, method, pathWithQuery, remote, status, cost
                );
            }
        }
    }
}
