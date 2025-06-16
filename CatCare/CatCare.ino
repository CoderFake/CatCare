#include "esp_camera.h"
#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <ESP32Servo.h>
#include "esp_timer.h"
#include "img_converters.h"
#include "Arduino.h"
#include "fb_gfx.h"
#include "soc/soc.h"
#include "soc/rtc_cntl_reg.h"

// Camera model AI Thinker ESP32-CAM
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

// CatCare Hardware pins
#define SERVO_PIN         2
#define GREEN_LED_PIN     12
#define RED_LED_PIN       13
#define BUZZER_PIN        14
#define SWITCH_PIN        15
#define RELAY_PIN         4

// RTSP includes
#include "OV2640.h"
#include "OV2640Streamer.h"
#include "CRtspSession.h"

// WiFi và MQTT config
const char* ssid = "YOUR_WIFI_NAME";
const char* password = "YOUR_WIFI_PASSWORD";
const char* mqtt_server = "broker.emqx.io";
const int mqtt_port = 1883;
const char* mqtt_client_id = "ESP32_CatCare_Device";

// MQTT Topics
const char* topic_feed = "catcare/feed";
const char* topic_mode = "catcare/mode";
const char* topic_status = "catcare/status";
const char* topic_feed_log = "catcare/feed_log";

// Global objects
WiFiClient espClient;
PubSubClient client(espClient);
Servo feedingServo;
OV2640 cam;

// RTSP server components
WiFiServer rtspServer(8554);
CStreamer *streamer = NULL;
CRtspSession *session = NULL;
WiFiClient rtspClient;

// System variables
String operatingMode = "manual";
unsigned long lastHeartbeat = 0;
unsigned long lastSwitchCheck = 0;
bool lastSwitchState = false;

const unsigned long HEARTBEAT_INTERVAL = 30000;
const unsigned long SWITCH_DEBOUNCE = 200;

// Task handles
TaskHandle_t rtspTaskHandler;
TaskHandle_t mqttTaskHandler;

void setup() {
    WRITE_PERI_REG(RTC_CNTL_BROWN_OUT_REG, 0);
    
    Serial.begin(115200);
    Serial.setDebugOutput(false);
    Serial.println("=== CatCare ESP32-CAM với RTSP Starting ===");
    
    setupHardware();
    setupCamera();
    connectWiFi();
    setupMQTT();
    startRTSP();
    
    // Tạo task cho MQTT
    xTaskCreatePinnedToCore(
        mqttTask,
        "MQTT Task",
        4096,
        NULL,
        1,
        &mqttTaskHandler,
        0
    );
    
    signalStartup();
    
    Serial.println("=== CatCare ESP32-CAM Ready ===");
    Serial.printf("RTSP Stream: rtsp://%s:8554/mjpeg/1\n", WiFi.localIP().toString().c_str());
}

void loop() {
    handleManualSwitch();
    delay(100);
}

void setupHardware() {
    pinMode(GREEN_LED_PIN, OUTPUT);
    pinMode(RED_LED_PIN, OUTPUT);
    pinMode(BUZZER_PIN, OUTPUT);
    pinMode(SWITCH_PIN, INPUT_PULLUP);
    pinMode(RELAY_PIN, OUTPUT);
    
    digitalWrite(GREEN_LED_PIN, LOW);
    digitalWrite(RED_LED_PIN, HIGH);
    digitalWrite(BUZZER_PIN, LOW);
    digitalWrite(RELAY_PIN, LOW);
    
    feedingServo.attach(SERVO_PIN);
    feedingServo.write(0);
    
    Serial.println("Hardware initialized");
}

void setupCamera() {
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
    
    if(psramFound()){
        config.frame_size = FRAMESIZE_VGA;
        config.jpeg_quality = 12;
        config.fb_count = 2;
    } else {
        config.frame_size = FRAMESIZE_SVGA;
        config.jpeg_quality = 12;
        config.fb_count = 1;
    }
    
    esp_err_t err = esp_camera_init(&config);
    if (err != ESP_OK) {
        Serial.printf("Camera init failed with error 0x%x", err);
        return;
    }
    
    // Khởi tạo OV2640 object cho RTSP
    cam.init(esp32cam_aithinker_config);
    
    Serial.println("Camera initialized successfully");
}

void connectWiFi() {
    WiFi.mode(WIFI_STA);
    WiFi.begin(ssid, password);
    Serial.print("Connecting to WiFi");
    
    while (WiFi.status() != WL_CONNECTED) {
        delay(500);
        Serial.print(".");
    }
    
    Serial.println("");
    Serial.println("WiFi connected");
    Serial.print("IP address: ");
    Serial.println(WiFi.localIP());
}

void setupMQTT() {
    client.setServer(mqtt_server, mqtt_port);
    client.setCallback(onMqttMessage);
}

void startRTSP() {
    xTaskCreatePinnedToCore(
        rtspTask,
        "RTSP Task",
        4096,
        NULL,
        2,
        &rtspTaskHandler,
        1
    );
    
    if (rtspTaskHandler == NULL) {
        Serial.println("Create RTSP task failed");
    } else {
        Serial.println("RTSP task created successfully");
    }
}

void rtspTask(void *pvParameters) {
    uint32_t msecPerFrame = 100;
    static uint32_t lastImage = millis();
    
    rtspServer.setTimeout(1);
    rtspServer.begin();
    Serial.println("RTSP Server started on port 8554");
    
    while (true) {
        if (session) {
            session->handleRequests(0);
            
            uint32_t now = millis();
            if (now > lastImage + msecPerFrame || now < lastImage) {
                session->broadcastCurrentFrame(now);
                lastImage = now;
            }
            
            if (session->m_stopped) {
                Serial.println("RTSP client disconnected");
                delete session;
                delete streamer;
                session = NULL;
                streamer = NULL;
            }
        } else {
            rtspClient = rtspServer.accept();
            if (rtspClient) {
                Serial.println("RTSP client connected");
                streamer = new OV2640Streamer(&rtspClient, cam);
                session = new CRtspSession(&rtspClient, streamer);
                delay(100);
            }
        }
        
        vTaskDelay(10 / portTICK_PERIOD_MS);
    }
}

void mqttTask(void *pvParameters) {
    while (true) {
        if (!client.connected()) {
            reconnectMQTT();
        }
        client.loop();
        sendHeartbeat();
        vTaskDelay(100 / portTICK_PERIOD_MS);
    }
}

void reconnectMQTT() {
    static unsigned long lastAttempt = 0;
    
    if (millis() - lastAttempt > 5000) {
        Serial.print("Attempting MQTT connection...");
        
        String clientId = "ESP32_CatCare_";
        clientId += String(random(0xffff), HEX);
        
        if (client.connect(clientId.c_str())) {
            Serial.println("connected");
            client.subscribe(topic_feed);
            client.subscribe(topic_mode);
            publishStatus("online");
        } else {
            Serial.print("failed, rc=");
            Serial.print(client.state());
            Serial.println(" will retry in 5 seconds");
        }
        lastAttempt = millis();
    }
}

void onMqttMessage(char* topic, byte* payload, unsigned int length) {
    String message;
    for (int i = 0; i < length; i++) {
        message += (char)payload[i];
    }
    
    Serial.printf("Message received [%s]: %s\n", topic, message.c_str());
    
    if (String(topic) == topic_feed) {
        activateFeeding(message);
    } else if (String(topic) == topic_mode) {
        operatingMode = message;
        Serial.printf("Mode changed to: %s\n", operatingMode.c_str());
    }
}

void activateFeeding(String mode) {
    Serial.printf("Feeding activated - Mode: %s\n", mode.c_str());
    
    digitalWrite(RELAY_PIN, HIGH);
    digitalWrite(GREEN_LED_PIN, HIGH);
    
    // Buzzer signal
    for (int i = 0; i < 5; i++) {
        digitalWrite(BUZZER_PIN, HIGH);
        delay(200);
        digitalWrite(BUZZER_PIN, LOW);
        delay(200);
    }
    
    // Servo operation
    unsigned long servoStartTime = millis();
    while (millis() - servoStartTime < 5000) {
        feedingServo.write(180);
        delay(500);
        feedingServo.write(0);
        delay(500);
    }
    
    digitalWrite(GREEN_LED_PIN, LOW);
    digitalWrite(RELAY_PIN, LOW);
    
    publishFeedingLog(mode);
    Serial.println("Feeding completed");
}

void handleManualSwitch() {
    if (millis() - lastSwitchCheck > SWITCH_DEBOUNCE) {
        bool currentSwitchState = !digitalRead(SWITCH_PIN);
        
        if (currentSwitchState && !lastSwitchState) {
            Serial.println("Manual switch pressed");
            activateFeeding("manual");
        }
        
        lastSwitchState = currentSwitchState;
        lastSwitchCheck = millis();
    }
}

void sendHeartbeat() {
    if (millis() - lastHeartbeat > HEARTBEAT_INTERVAL) {
        publishStatus("online");
        lastHeartbeat = millis();
    }
}

void publishStatus(String status) {
    DynamicJsonDocument doc(300);
    doc["status"] = status;
    doc["mode"] = operatingMode;
    doc["timestamp"] = millis();
    doc["device"] = "esp32_cam";
    doc["wifi_rssi"] = WiFi.RSSI();
    doc["rtsp_url"] = "rtsp://" + WiFi.localIP().toString() + ":8554/mjpeg/1";
    doc["free_heap"] = ESP.getFreeHeap();
    
    String jsonString;
    serializeJson(doc, jsonString);
    
    client.publish(topic_status, jsonString.c_str());
}

void publishFeedingLog(String mode) {
    DynamicJsonDocument doc(200);
    doc["mode"] = mode;
    doc["timestamp"] = millis();
    doc["device"] = "esp32_cam";
    doc["success"] = true;
    
    String jsonString;
    serializeJson(doc, jsonString);
    
    client.publish(topic_feed_log, jsonString.c_str());
}

void signalStartup() {
    for (int i = 0; i < 3; i++) {
        digitalWrite(GREEN_LED_PIN, HIGH);
        digitalWrite(BUZZER_PIN, HIGH);
        delay(300);
        digitalWrite(GREEN_LED_PIN, LOW);
        digitalWrite(BUZZER_PIN, LOW);
        delay(200);
    }
    
    // Final status
    digitalWrite(RED_LED_PIN, LOW);
    digitalWrite(GREEN_LED_PIN, HIGH);
    delay(1000);
    digitalWrite(GREEN_LED_PIN, LOW);
}