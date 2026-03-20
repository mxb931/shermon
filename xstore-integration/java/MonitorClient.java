package com.xstore.monitor;

import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;

public class MonitorClient {
    private final HttpClient client;
    private final String ingestUrl;
    private final String apiKey;

    public MonitorClient(String ingestUrl, String apiKey) {
        this.client = HttpClient.newBuilder()
                .connectTimeout(Duration.ofSeconds(2))
                .build();
        this.ingestUrl = ingestUrl;
        this.apiKey = apiKey;
    }

    public boolean postEvent(String jsonPayload) throws IOException, InterruptedException {
        HttpRequest request = HttpRequest.newBuilder()
                .uri(URI.create(ingestUrl))
                .header("Content-Type", "application/json")
                .header("X-Monitor-Key", apiKey)
                .timeout(Duration.ofSeconds(3))
                .POST(HttpRequest.BodyPublishers.ofString(jsonPayload))
                .build();

        HttpResponse<String> response = client.send(request, HttpResponse.BodyHandlers.ofString());
        return response.statusCode() >= 200 && response.statusCode() < 300;
    }
}
