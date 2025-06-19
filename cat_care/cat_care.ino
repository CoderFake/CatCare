#include "esp_camera.h"
#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include "esp_timer.h"
#include "img_converters.h"
#include "Arduino.h"
#include "fb_gfx.h"
#include "soc/soc.h"
#include "soc/rtc_cntl_reg.h"

#include <ESP32-RTSPServer.h>

#define CAMERA_MODEL_AI_THINKER
#define PWDN_GPIO_NUM     32
#define RESET_GPIO_NUM    -1
#define XCLK_GPIO_NUM      0
#define SIOD_GPIO_NUM     26
#define SIOC_GPIO_NUM     27
#define Y9_GPIO_NUM       35
#define Y8_GPIO_NUM       34
#define Y7_GPIO_NUM       39
#define Y6_GPIO_NUM       36
#define Y5_GPIO_NUM       21
#define Y4_GPIO_NUM       19
#define Y3_GPIO_NUM       18
#define Y2_GPIO_NUM        5
#define VSYNC_GPIO_NUM    25
#define HREF_GPIO_NUM     23
#define PCLK_GPIO_NUM     22

#include "wifikeys.h"

const char* mqtt_server = "broker.emqx.io";
const int mqtt_port = 1883;
const char* topic_camera_status = "catcare/camera_status";

WiFiClient espClient;
PubSubClient client(espClient);
RTSPServer rtspServer;

int quality = 15;
unsigned long lastHeartbeat = 0;
const unsigned long HEARTBEAT_INTERVAL = 30000;

TaskHandle_t videoTaskHandle = NULL;
TaskHandle_t mqttTaskHandle = NULL;

bool setupCamera();
void connectWiFi();
void setupMQTT();
void mqttTask(void *pvParameters);
void reconnectMQTT();
void publishCameraStatus();
void sendVideo(void* pvParameters);
void setupRTSP();
void getFrameQuality();

void setup() {
    WRITE_PERI_REG(RTC_CNTL_BROWN_OUT_REG, 0);
    
    Serial.begin(115200);
    Serial.setDebugOutput(false);
    Serial.println("=== CatCare ESP32-CAM RTSP Server Starting ===");
    
    if (setupCamera()) {
        Serial.println("[SETUP] Camera initialized successfully");
        getFrameQuality();
    } else {
        Serial.println("[SETUP] Camera initialization failed!");
        return;
    }
    
    connectWiFi();
    setupMQTT();
    setupRTSP();
    
    Serial.println("[SETUP] Creating MQTT task...");
    xTaskCreatePinnedToCore(
        mqttTask,
        "MQTT Task",
        4096,
        NULL,
        1,
        &mqttTaskHandle,
        0
    );
    
    Serial.println("[SETUP] Creating Video task...");
    xTaskCreatePinnedToCore(
        sendVideo,
        "Video Task",
        8192,
        NULL,
        9,
        &videoTaskHandle,
        0
    );
    
    Serial.println("[SETUP] Waiting for MQTT connection...");
    int retries = 0;
    while (!client.connected() && retries < 10) {
        Serial.printf("[SETUP] Waiting for MQTT... Attempt %d/10\n", retries + 1);
        delay(1000);
        retries++;
    }
    
    if (client.connected()) {
        Serial.println("[SETUP] MQTT connected! Publishing camera status...");
        publishCameraStatus();
        delay(1000);
    }
    
    Serial.println("=== CatCare ESP32-CAM RTSP Server Ready ===");
    Serial.printf("RTSP Stream: rtsp://%s:8554/\n", WiFi.localIP().toString().c_str());
}

void loop() {
    static unsigned long lastMemCheck = 0;
    
    if (millis() - lastMemCheck > 5000) {
        Serial.printf("[STATUS] Heap: %d bytes, FPS: %lu\n", ESP.getFreeHeap(), rtspServer.rtpFps);
        Serial.printf("[STATUS] WiFi: %s (Status: %d), IP: %s\n",
                      WiFi.status() == WL_CONNECTED ? "Connected" : "Disconnected",
                      WiFi.status(),
                      WiFi.localIP().toString().c_str());
        Serial.printf("[STATUS] MQTT Connected: %s\n", client.connected() ? "YES" : "NO");
        lastMemCheck = millis();
    }
    
    yield();
    delay(100);
}

void getFrameQuality() { 
    sensor_t * s = esp_camera_sensor_get(); 
    quality = s->status.quality; 
    Serial.printf("Camera Quality is: %d\n", quality);
}

void sendVideo(void* pvParameters) { 
    while (true) { 
        if(rtspServer.readyToSendFrame()) {
            camera_fb_t* fb = esp_camera_fb_get();
            if (fb) {
                rtspServer.sendRTSPFrame(fb->buf, fb->len, quality, fb->width, fb->height);
                esp_camera_fb_return(fb);
            }
        }
        vTaskDelay(pdMS_TO_TICKS(33)); // ~30 FPS
    }
}



bool setupCamera() {
    esp_camera_deinit();
    delay(1000);
    
    camera_config_t config;
    config.ledc_channel = LEDC_CHANNEL_0;
    config.ledc_timer = LEDC_TIMER_0;
    config.pin_d0 = Y2_GPIO_NUM;
    config.pin_d1 = Y3_GPIO_NUM;
    config.pin_d2 = Y4_GPIO_NUM;
    config.pin_d3 = Y5_GPIO_NUM;
    config.pin_d4 = Y6_GPIO_NUM;
    config.pin_d5 = Y7_GPIO_NUM;
    config.pin_d6 = Y8_GPIO_NUM;
    config.pin_d7 = Y9_GPIO_NUM;
    config.pin_xclk = XCLK_GPIO_NUM;
    config.pin_pclk = PCLK_GPIO_NUM;
    config.pin_vsync = VSYNC_GPIO_NUM;
    config.pin_href = HREF_GPIO_NUM;
    config.pin_sscb_sda = SIOD_GPIO_NUM;
    config.pin_sscb_scl = SIOC_GPIO_NUM;
    config.pin_pwdn = PWDN_GPIO_NUM;
    config.pin_reset = RESET_GPIO_NUM;
    config.xclk_freq_hz = 20000000;
    config.pixel_format = PIXFORMAT_JPEG;
    config.grab_mode = CAMERA_GRAB_LATEST;
    config.fb_location = CAMERA_FB_IN_PSRAM;
    config.jpeg_quality = 10;
    config.fb_count = 2;
    
    if(psramFound()){
        config.frame_size = FRAMESIZE_VGA;         
    } else {
        config.frame_size = FRAMESIZE_QVGA;
        config.fb_location = CAMERA_FB_IN_DRAM;
    }
    
    esp_err_t err = esp_camera_init(&config);
    if (err != ESP_OK) {
        Serial.printf("Camera init failed with error 0x%x\n", err);
        return false;
    }
    
    sensor_t *s = esp_camera_sensor_get();
    if (s->id.PID == OV3660_PID) {
        s->set_vflip(s, 1);
        s->set_brightness(s, 1);
        s->set_saturation(s, -2);
    }
    
    if (config.pixel_format == PIXFORMAT_JPEG) {
        s->set_framesize(s, FRAMESIZE_VGA);
    }
    
    delay(2000);
    
    camera_fb_t * fb = esp_camera_fb_get();
    if (!fb) {
        Serial.println("Camera test failed");
        return false;
    }
    Serial.printf("Camera test OK: %d bytes\n", fb->len);
    esp_camera_fb_return(fb);
    
    Serial.printf("Camera ready: %dx%d, Quality: %d, PSRAM: %s\n", 
                  psramFound() ? 640 : 320,
                  psramFound() ? 480 : 240,
                  10,
                  psramFound() ? "YES" : "NO");
    
    return true;
}

void connectWiFi() {
    Serial.println("[WiFi] Starting WiFi connection...");
    WiFi.mode(WIFI_STA);
    WiFi.begin(ssid, password);
    Serial.printf("[WiFi] Connecting to SSID: %s", ssid);
    
    int attempts = 0;
    while (WiFi.status() != WL_CONNECTED && attempts < 30) {
        delay(500);
        Serial.print(".");
        attempts++;
        
        if (attempts % 10 == 0) {
            Serial.printf("\n[WiFi] Attempt %d/30, Status: %d\n", attempts, WiFi.status());
        }
    }
    
    if (WiFi.status() == WL_CONNECTED) {
        Serial.println("");
        Serial.println("[WiFi] WiFi connected successfully!");
        Serial.printf("[WiFi] IP address: %s\n", WiFi.localIP().toString().c_str());
        Serial.printf("[WiFi] RSSI: %d dBm\n", WiFi.RSSI());
        Serial.printf("[WiFi] Gateway: %s\n", WiFi.gatewayIP().toString().c_str());
    } else {
        Serial.println("");
        Serial.printf("[WiFi] WiFi connection failed! Final status: %d\n", WiFi.status());
    }
}

void setupMQTT() {
    client.setServer(mqtt_server, mqtt_port);
    client.setBufferSize(512);
    Serial.printf("[MQTT] Server configured: %s:%d\n", mqtt_server, mqtt_port);
}

void setupRTSP() {
    rtspServer.maxRTSPClients = 3;
    rtspServer.setCredentials("", "");
    
    if (rtspServer.init(RTSPServer::VIDEO_ONLY, 8554)) { 
        Serial.printf("RTSP server started successfully on port 8554\n");
    } else { 
        Serial.println("Failed to start RTSP server"); 
    }
}

void mqttTask(void *pvParameters) {
    while (true) {
        if (!client.connected()) {
            Serial.println("[MQTT] Client not connected, attempting reconnect...");
            reconnectMQTT();
        }
        
        if (client.connected()) {
            client.loop();
            
            // Gửi heartbeat và camera status
            if (millis() - lastHeartbeat > HEARTBEAT_INTERVAL) {
                Serial.println("[MQTT] Sending camera status...");
                publishCameraStatus();
                lastHeartbeat = millis();
            }
        }
        
        vTaskDelay(1000 / portTICK_PERIOD_MS);
    }
}

void reconnectMQTT() {
    static unsigned long lastAttempt = 0;
    
    if (millis() - lastAttempt > 5000) {
        Serial.print("[MQTT] Attempting connection to ");
        Serial.print(mqtt_server);
        Serial.print(":");
        Serial.print(mqtt_port);
        Serial.print("...");
        
        String clientId = "ESP32_CatCare_Camera_";
        clientId += String(random(0xffff), HEX);
        Serial.printf(" ClientID: %s\n", clientId.c_str());
        
        if (client.connect(clientId.c_str())) {
            Serial.println("[MQTT] Connected successfully!");
            publishCameraStatus();
        } else {
            Serial.print("[MQTT] Connection failed, rc=");
            Serial.print(client.state());
            Serial.printf(" WiFi status: %d\n", WiFi.status());
            Serial.println("[MQTT] Will retry in 5 seconds");
        }
        lastAttempt = millis();
    }
}

void publishCameraStatus() {
    if (!client.connected()) {
        Serial.println("[MQTT] ERROR: MQTT client not connected!");
        return;
    }
    
    DynamicJsonDocument doc(256);
    doc["device"] = "esp32_cam";
    doc["status"] = "online";
    doc["rtsp_url"] = "rtsp://" + WiFi.localIP().toString() + ":8554/";
    doc["ip"] = WiFi.localIP().toString();
    doc["fps"] = rtspServer.rtpFps;
    doc["free_heap"] = ESP.getFreeHeap();
    doc["quality"] = quality;
    doc["timestamp"] = millis();
    
    String jsonString;
    serializeJson(doc, jsonString);
    
    Serial.printf("[MQTT] Publishing camera status: %s\n", jsonString.c_str());
    
    bool result = client.publish(topic_camera_status, jsonString.c_str(), true);
    
    if (result) {
        Serial.println("[MQTT] Camera status published successfully!");
    } else {
        Serial.println("[MQTT] Failed to publish camera status!");
        Serial.printf("[MQTT] Client state: %d\n", client.state());
    }
}