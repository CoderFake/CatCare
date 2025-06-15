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
#include "esp_http_server.h"

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

#define SERVO_PIN         2
#define GREEN_LED_PIN     12
#define RED_LED_PIN       13
#define BUZZER_PIN        14
#define SWITCH_PIN        15

#define PART_BOUNDARY "123456789000000000000987654321"

const char* ssid = "Disconnect";
const char* password = "2444666668888888";

const char* mqtt_server = "broker.emqx.io";
const int mqtt_port = 1883;
const char* mqtt_client_id = "ESP32_CatCare_Device";

const char* topic_feed = "catcare/feed";
const char* topic_mode = "catcare/mode";
const char* topic_status = "catcare/status";
const char* topic_feed_log = "catcare/feed_log";

WiFiClient espClient;
PubSubClient client(espClient);
Servo feedingServo;

String operatingMode = "manual";
unsigned long lastHeartbeat = 0;
unsigned long lastSwitchCheck = 0;

const unsigned long HEARTBEAT_INTERVAL = 30000;
const unsigned long SWITCH_DEBOUNCE = 200;

bool lastSwitchState = false;

void mqttTask(void *pvParameters);

static const char* _STREAM_CONTENT_TYPE = "multipart/x-mixed-replace;boundary=" PART_BOUNDARY;
static const char* _STREAM_BOUNDARY = "\r\n--" PART_BOUNDARY "\r\n";
static const char* _STREAM_PART = "Content-Type: image/jpeg\r\nContent-Length: %u\r\n\r\n";

httpd_handle_t stream_httpd = NULL;

static esp_err_t stream_handler(httpd_req_t *req){
  camera_fb_t * fb = NULL;
  esp_err_t res = ESP_OK;
  size_t _jpg_buf_len = 0;
  uint8_t * _jpg_buf = NULL;
  char * part_buf[64];

  res = httpd_resp_set_type(req, _STREAM_CONTENT_TYPE);
  if(res != ESP_OK){
    return res;
  }

  while(true){
    fb = esp_camera_fb_get();
    if (!fb) {
      Serial.println("Camera capture failed");
      res = ESP_FAIL;
      break;
    } else {
      _jpg_buf_len = fb->len;
      _jpg_buf = fb->buf;
    }
    if(res == ESP_OK){
      size_t hlen = snprintf((char *)part_buf, 64, _STREAM_PART, _jpg_buf_len);
      res = httpd_resp_send_chunk(req, (const char *)part_buf, hlen);
    }
    if(res == ESP_OK){
      res = httpd_resp_send_chunk(req, (const char *)_jpg_buf, _jpg_buf_len);
    }
    if(res == ESP_OK){
      res = httpd_resp_send_chunk(req, _STREAM_BOUNDARY, strlen(_STREAM_BOUNDARY));
    }
    if(fb){
      esp_camera_fb_return(fb);
      fb = NULL;
      _jpg_buf = NULL;
    }
    if(res != ESP_OK){
      break;
    }
    vTaskDelay(50 / portTICK_PERIOD_MS);
  }
  return res;
}

void startCameraServer(){
  httpd_config_t config = HTTPD_DEFAULT_CONFIG();
  config.server_port = 80;

  httpd_uri_t stream_uri = {
    .uri       = "/stream",
    .method    = HTTP_GET,
    .handler   = stream_handler,
    .user_ctx  = NULL
  };
  
  Serial.printf("Starting web server on port: '%d'\n", config.server_port);
  if (httpd_start(&stream_httpd, &config) == ESP_OK) {
    httpd_register_uri_handler(stream_httpd, &stream_uri);
  }
}

void setup() {
  WRITE_PERI_REG(RTC_CNTL_BROWN_OUT_REG, 0);
  
  Serial.begin(115200);
  Serial.setDebugOutput(false);
  Serial.println("=== CatCare ESP32-CAM Starting ===");
  
  setupHardware();
  setupCamera();
  connectWiFi();
  startCameraServer();
  setupMQTT();
  
  xTaskCreatePinnedToCore(
    mqttTask,
    "MQTT Task",
    4096,
    NULL,
    1,
    NULL,
    0
  );
  
  signalStartup();
  
  Serial.println("=== CatCare ESP32-CAM Ready ===");
  Serial.printf("Camera Stream Ready! Go to: http://%s/stream\n", WiFi.localIP().toString().c_str());
}

void loop() {
  handleManualSwitch();
  delay(1);
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

void setupHardware() {
  pinMode(GREEN_LED_PIN, OUTPUT);
  pinMode(RED_LED_PIN, OUTPUT);
  pinMode(BUZZER_PIN, OUTPUT);
  pinMode(SWITCH_PIN, INPUT_PULLUP);
  
  digitalWrite(GREEN_LED_PIN, LOW);
  digitalWrite(RED_LED_PIN, HIGH);
  digitalWrite(BUZZER_PIN, LOW);
  
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
    config.jpeg_quality = 30;
    config.fb_count = 2;
  } else {
    config.frame_size = FRAMESIZE_VGA;
    config.jpeg_quality = 35;
    config.fb_count = 1;
  }
  
  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    Serial.printf("Camera init failed with error 0x%x", err);
    return;
  }
  
  Serial.println("Camera initialized");
}

void connectWiFi() {
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

void reconnectMQTT() {
  static unsigned long lastAttempt = 0;
  
  if (millis() - lastAttempt > 5000) {
    Serial.print("Attempting MQTT connection...");
    
    if (client.connect(mqtt_client_id)) {
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
  
  digitalWrite(GREEN_LED_PIN, HIGH);
  
  for (int i = 0; i < 5; i++) {
    digitalWrite(BUZZER_PIN, HIGH);
    delay(200);
    digitalWrite(BUZZER_PIN, LOW);
    delay(200);
  }
  
  unsigned long servoStartTime = millis();
  while (millis() - servoStartTime < 5000) {
    feedingServo.write(180);
    delay(500);
    feedingServo.write(0);
    delay(500);
  }
  
  digitalWrite(GREEN_LED_PIN, LOW);
  
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
  DynamicJsonDocument doc(200);
  doc["status"] = status;
  doc["mode"] = operatingMode;
  doc["timestamp"] = millis();
  doc["device"] = "esp32_cam";
  doc["wifi_rssi"] = WiFi.RSSI();
  doc["stream_url"] = "http://" + WiFi.localIP().toString() + "/stream";
  
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