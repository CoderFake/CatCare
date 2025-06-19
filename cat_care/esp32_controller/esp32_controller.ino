#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>

#define SERVO_PIN         18
#define GREEN_LED_PIN     12
#define RED_LED_PIN       15
#define BUZZER_PIN        14
#define SWITCH_PIN        4

const int PWM_CHANNEL = 0;
const int PWM_FREQ = 50;
const int PWM_RESOLUTION = 16;

#include "wifikeys.h"

const char* mqtt_server = "broker.emqx.io";
const int mqtt_port = 1883;

const char* topic_feed = "catcare/feed";
const char* topic_mode = "catcare/mode";
const char* topic_status = "catcare/status";
const char* topic_feed_log = "catcare/feed_log";

WiFiClient espClient;
PubSubClient client(espClient);

String operatingMode = "manual";
unsigned long lastHeartbeat = 0;
unsigned long lastSwitchCheck = 0;
bool lastSwitchState = false;
int dailyFeedCount = 0;
unsigned long lastFeedTime = 0;

const unsigned long HEARTBEAT_INTERVAL = 30000;
const unsigned long SWITCH_DEBOUNCE = 200;
const unsigned long MIN_FEED_INTERVAL = 60000;
const int MAX_DAILY_FEEDS = 30;

TaskHandle_t mqttTaskHandler;

void setupHardware();
void connectWiFi();
void setupMQTT();
void mqttTask(void *pvParameters);
void reconnectMQTT();
void onMqttMessage(char* topic, byte* payload, unsigned int length);
void activateFeeding(String mode);
void handleManualSwitch();
void sendHeartbeat();
void publishStatus(String status);
void publishFeedingLog(String mode);
void signalStartup();
void setServoAngle(int angle);

void setup() {
    Serial.begin(115200);
    Serial.setDebugOutput(false);
    Serial.println("=== CatCare ESP32 MQTT Controller Starting ===");
    
    setupHardware();
    connectWiFi();
    setupMQTT();

    Serial.println("[SETUP] Creating MQTT task...");
    xTaskCreatePinnedToCore(
        mqttTask,
        "MQTT Task",
        8192,
        NULL,
        1,
        &mqttTaskHandler,
        0
    );
    
    signalStartup();
    
    Serial.println("[SETUP] Waiting for MQTT connection...");
    int retries = 0;
    while (!client.connected() && retries < 10) {
        Serial.printf("[SETUP] Waiting for MQTT... Attempt %d/10\n", retries + 1);
        delay(1000);
        retries++;
    }
    
    if (client.connected()) {
        Serial.println("[SETUP] MQTT connected! Publishing initial status...");
        publishStatus("online");
        delay(1000);
        Serial.println("[SETUP] Initial status sent");
    } else {
        Serial.println("[SETUP] MQTT connection failed after retries");
    }
    
    Serial.println("=== CatCare ESP32 MQTT Controller Ready ===");
}

void loop() {
    handleManualSwitch();
    
    static unsigned long lastMemCheck = 0;
    static unsigned long lastMqttCheck = 0;
    
    if (millis() - lastMemCheck > 5000) {
        Serial.printf("[STATUS] Heap: %d bytes\n", ESP.getFreeHeap());
        lastMemCheck = millis();
    }
    
    if (millis() - lastMqttCheck > 15000) {
        Serial.printf("[STATUS] MQTT Connected: %s, WiFi: %s (Status: %d), IP: %s\n",
                      client.connected() ? "YES" : "NO",
                      WiFi.status() == WL_CONNECTED ? "Connected" : "Disconnected",
                      WiFi.status(),
                      WiFi.localIP().toString().c_str());
        
        if (client.connected()) {
            Serial.printf("[STATUS] Next heartbeat in: %lu ms\n", 
                          HEARTBEAT_INTERVAL - (millis() - lastHeartbeat));
        }
        
        lastMqttCheck = millis();
    }
    
    yield();
    delay(100);
}

void setupHardware() {
    pinMode(GREEN_LED_PIN, OUTPUT);
    pinMode(RED_LED_PIN, OUTPUT);
    pinMode(BUZZER_PIN, OUTPUT);
    pinMode(SWITCH_PIN, INPUT_PULLUP);
    
    digitalWrite(GREEN_LED_PIN, LOW); 
    digitalWrite(RED_LED_PIN, HIGH); 
    digitalWrite(BUZZER_PIN, LOW);
    
    ledcSetup(PWM_CHANNEL, PWM_FREQ, PWM_RESOLUTION);
    ledcAttachPin(SERVO_PIN, PWM_CHANNEL);
    
    Serial.printf("[SERVO] PWM servo attached to pin %d\n", SERVO_PIN);
    
    Serial.println("[SERVO] Setting servo to initial position (0°)...");
    setServoAngle(0);
    delay(1000);
    
    Serial.println("[SERVO] Servo initialized at 0°");
    Serial.println("Hardware initialized");
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
    client.setCallback(onMqttMessage);
    client.setBufferSize(512);
}

void mqttTask(void *pvParameters) {
    while (true) {
        if (!client.connected()) {
            Serial.println("[MQTT] Client not connected, attempting reconnect...");
            reconnectMQTT();
        }
        
        if (client.connected()) {
            client.loop();
            sendHeartbeat();
        } else {
            Serial.println("[MQTT] Still not connected after reconnect attempt");
        }
        
        vTaskDelay(100 / portTICK_PERIOD_MS);
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
        
        String clientId = "ESP32_CatCare_Controller_";
        clientId += String(random(0xffff), HEX);
        Serial.printf(" ClientID: %s\n", clientId.c_str());
        
        if (client.connect(clientId.c_str())) {
            Serial.println("[MQTT] Connected successfully!");
            
            Serial.printf("[MQTT] Subscribing to %s... ", topic_feed);
            int result1 = client.subscribe(topic_feed);
            Serial.printf("Result: %d\n", result1);
            
            Serial.printf("[MQTT] Subscribing to %s... ", topic_mode);
            int result2 = client.subscribe(topic_mode);
            Serial.printf("Result: %d\n", result2);
            
            Serial.println("[MQTT] Publishing initial status...");
            publishStatus("online");
        } else {
            Serial.print("[MQTT] Connection failed, rc=");
            Serial.print(client.state());
            Serial.printf(" WiFi status: %d\n", WiFi.status());
            Serial.println("[MQTT] Will retry in 5 seconds");
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
    if (dailyFeedCount >= MAX_DAILY_FEEDS) {
        Serial.println("Daily feeding limit reached!");
        return;
    }
    
    Serial.printf("Feeding activated - Mode: %s\n", mode.c_str());
    
    digitalWrite(RED_LED_PIN, LOW);
    digitalWrite(GREEN_LED_PIN, HIGH);
    
    for (int i = 0; i < 5; i++) {
        digitalWrite(BUZZER_PIN, HIGH);
        delay(200);
        digitalWrite(BUZZER_PIN, LOW);
        delay(200);
    }
    
    Serial.println("[SERVO] Moving to feeding position (0° → 180°)...");
    setServoAngle(0);
    delay(500);
    setServoAngle(180);
    Serial.println("[SERVO] Reached 180°, waiting 5 seconds...");
    
    delay(5000);
    
    Serial.println("[SERVO] Returning to closed position (180° → 0°)...");
    setServoAngle(0);
    Serial.println("[SERVO] Returned to 0°");
    
    delay(500);
    
    digitalWrite(GREEN_LED_PIN, LOW);
    digitalWrite(RED_LED_PIN, HIGH);
    
    dailyFeedCount++;
    lastFeedTime = millis();
    
    publishFeedingLog(mode);
    Serial.printf("Feeding completed. Daily count: %d\n", dailyFeedCount);
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
    static unsigned long heartbeatCount = 0;
    
    if (millis() - lastHeartbeat > HEARTBEAT_INTERVAL) {
        heartbeatCount++;
        Serial.printf("[HEARTBEAT] #%lu - Time since last: %lu ms\n", 
                      heartbeatCount, millis() - lastHeartbeat);
        
        if (client.connected()) {
            Serial.println("[HEARTBEAT] MQTT connected, sending status...");
            publishStatus("online");
        } else {
            Serial.println("[HEARTBEAT] MQTT NOT connected, skipping status");
        }
        
        lastHeartbeat = millis();
    }
}

void publishStatus(String status) {
    Serial.printf("[PUBLISH] Creating status message with status: %s\n", status.c_str());
    
    if (!client.connected()) {
        Serial.println("[PUBLISH] ERROR: MQTT client not connected!");
        return;
    }
    
    DynamicJsonDocument doc(256);
    doc["status"] = status;
    doc["mode"] = operatingMode;
    doc["device"] = "esp32_controller";
    doc["free_heap"] = ESP.getFreeHeap();
    doc["daily_feeds"] = dailyFeedCount;
    doc["timestamp"] = millis();
    
    String jsonString;
    serializeJson(doc, jsonString);
    
    Serial.printf("[PUBLISH] JSON payload (%d bytes): %s\n", jsonString.length(), jsonString.c_str());
    Serial.printf("[PUBLISH] Publishing to topic: %s\n", topic_status);
    
    bool result = client.publish(topic_status, jsonString.c_str(), true);
    
    if (result) {
        Serial.println("[PUBLISH] Status published successfully!");
    } else {
        Serial.println("[PUBLISH] Failed to publish status!");
        Serial.printf("[PUBLISH] Client state: %d\n", client.state());
    }
}

void publishFeedingLog(String mode) {
    DynamicJsonDocument doc(256);
    doc["mode"] = mode;
    doc["device"] = "esp32_controller";
    doc["success"] = true;
    doc["daily_count"] = dailyFeedCount;
    doc["timestamp"] = millis();
    
    String jsonString;
    serializeJson(doc, jsonString);
    
    Serial.printf("[FEED_LOG] Publishing: %s\n", jsonString.c_str());
    client.publish(topic_feed_log, jsonString.c_str());
}

void signalStartup() {
    digitalWrite(BUZZER_PIN, HIGH);
    delay(1000);
    digitalWrite(BUZZER_PIN, LOW);
    
    digitalWrite(RED_LED_PIN, HIGH);
    digitalWrite(GREEN_LED_PIN, LOW);
}

void setServoAngle(int angle) {
    int dutyCycle = map(angle, 0, 180, 1638, 8191);
    ledcWrite(PWM_CHANNEL, dutyCycle);
    Serial.printf("[SERVO] Góc: %d°, Duty cycle: %d\n", angle, dutyCycle);
}