#include "esp_camera.h"
#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <ESP32Servo.h>
#include <base64.h>
#include <WebServer.h>

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

#define SERVO_PIN         2
#define GREEN_LED_PIN     12
#define RED_LED_PIN       13
#define BUZZER_PIN        14
#define SWITCH_PIN        15
#define RELAY_PIN         4

const char* ssid = "YOUR_WIFI_NAME";
const char* password = "YOUR_WIFI_PASSWORD";

const char* mqtt_server = "broker.emqx.io";
const int mqtt_port = 1883;
const char* mqtt_client_id = "ESP32_CatCare_Device";

const char* topic_feed = "catcare/feed";
const char* topic_mode = "catcare/mode";
const char* topic_status = "catcare/status";
const char* topic_image = "catcare/image";
const char* topic_feed_log = "catcare/feed_log";
const char* topic_image_chunk = "catcare/image_chunk";

WiFiClient espClient;
PubSubClient client(espClient);
Servo feedingServo;

String operatingMode = "manual";
bool deviceConnected = false;
unsigned long lastHeartbeat = 0;
unsigned long lastImageSend = 0;
unsigned long lastSwitchCheck = 0;

const unsigned long HEARTBEAT_INTERVAL = 30000;
const unsigned long IMAGE_INTERVAL = 2000;
const unsigned long SWITCH_DEBOUNCE = 200;

bool switchState = false;
bool lastSwitchState = false;

void setup() {
  Serial.begin(115200);
  Serial.println("=== CatCare ESP32-CAM Starting ===");
  
  setupHardware();
  
  if (setupCamera()) {
    Serial.println("Camera initialized successfully");
  } else {
    Serial.println("Camera initialization FAILED!");
    while(1) delay(1000);
  }
  
  connectWiFi();
  setupMQTT();
  signalStartup();
  
  deviceConnected = true;
  Serial.println("=== CatCare ESP32-CAM Ready ===");
}

void loop() {
  if (!client.connected()) {
    reconnectMQTT();
  }
  client.loop();
  
  handleManualSwitch();
  sendHeartbeat();
  captureAndSendImage();
  
  delay(50);
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
  delay(500);
  
  Serial.println("Hardware initialized");
}

bool setupCamera() {
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
    config.jpeg_quality = 15;
    config.fb_count = 2;
  } else {
    config.frame_size = FRAMESIZE_QVGA;
    config.jpeg_quality = 20;
    config.fb_count = 1;
  }
  
  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    Serial.printf("Camera init failed: 0x%x\n", err);
    return false;
  }
  
  sensor_t * s = esp_camera_sensor_get();
  s->set_brightness(s, 0);
  s->set_contrast(s, 0);
  s->set_saturation(s, 0);
  s->set_special_effect(s, 0);
  s->set_whitebal(s, 1);
  s->set_awb_gain(void connectWiFi() {
  WiFi.begin(ssid, password);
  Serial.print("Connecting to WiFi");
  
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  
  Serial.println();
  Serial.print("WiFi connected! IP: ");
  Serial.println(WiFi.localIP());
}

void setupMQTT() {
  client.setServer(mqtt_server, mqtt_port);
  client.setCallback(onMqttMessage);
  client.setBufferSize(32768);
}

void reconnectMQTT() {
  while (!client.connected()) {
    Serial.print("Attempting MQTT connection...");
    
    if (client.connect(mqtt_client_id)) {
      Serial.println("connected");
      client.subscribe(topic_feed);
      client.subscribe(topic_mode);
      publishStatus("online");
    } else {
      Serial.print("failed, rc=");
      Serial.print(client.state());
      Serial.println(" try again in 5 seconds");
      delay(5000);
    }
  }
}

void onMqttMessage(char* topic, byte* payload, unsigned int length) {
  String message;
  for (int i = 0; i < length; i++) {
    message += (char)payload[i];
  }
  
  Serial.printf("Message received [%s]: %s\n", topic, message.c_str());
  
  if (String(topic) == topic_feed) {
    String mode = message;
    activateFeeding(mode);
  } else if (String(topic) == topic_mode) {
    operatingMode = message;
    Serial.printf("Mode changed to: %s\n", operatingMode.c_str());
  }
}

void activateFeeding(String mode) {
  Serial.printf("Feeding activated - Mode: %s\n", mode.c_str());
  
  digitalWrite(RELAY_PIN, HIGH);
  delay(100);
  
  digitalWrite(GREEN_LED_PIN, HIGH);
  
  for (int i = 0; i < 5; i++) {
    digitalWrite(BUZZER_PIN, HIGH);
    delay(200);
    digitalWrite(BUZZER_PIN, LOW);
    delay(200);
  }
  
  unsigned long servoStartTime = millis();
  while (millis() - servoStartTime < 5000) {
    feedingServo.write(90);
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

void captureAndSendImage() {
  if (millis() - lastImageSend > IMAGE_INTERVAL) {
    camera_fb_t * fb = esp_camera_fb_get();
    if (!fb) {
      Serial.println("Camera capture failed");
      return;
    }
    
    String imageBase64 = base64::encode(fb->buf, fb->len);
    
    DynamicJsonDocument doc(imageBase64.length() + 200);
    doc["image"] = imageBase64;
    doc["timestamp"] = millis();
    doc["format"] = "jpeg";
    doc["device"] = "esp32_cam";
    
    String jsonString;
    serializeJson(doc, jsonString);
    
    if (jsonString.length() > 8192) {
      sendImageInChunks(jsonString);
    } else {
      client.publish(topic_image, jsonString.c_str());
    }
    
    esp_camera_fb_return(fb);
    lastImageSend = millis();
  }
}

void sendImageInChunks(String data) {
  int chunkSize = 8000;
  int totalChunks = (data.length() + chunkSize - 1) / chunkSize;
  
  for (int i = 0; i < totalChunks; i++) {
    String chunk = data.substring(i * chunkSize, min((i + 1) * chunkSize, (int)data.length()));
    
    DynamicJsonDocument chunkDoc(chunkSize + 100);
    chunkDoc["chunk"] = i;
    chunkDoc["total"] = totalChunks;
    chunkDoc["data"] = chunk;
    
    String chunkJson;
    serializeJson(chunkDoc, chunkJson);
    
    client.publish(topic_image_chunk, chunkJson.c_str());
    delay(50);
  }
}

void publishStatus(String status) {
  DynamicJsonDocument doc(200);
  doc["status"] = status;
  doc["mode"] = operatingMode;
  doc["timestamp"] = millis();
  doc["device"] = "esp32_cam";
  doc["wifi_rssi"] = WiFi.RSSI();
  
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
}