#include "main.h"

/** Put your WiFi credentials into this file **/
#include "wifikeys.h"

//mqtt broker - mqtt_server
//const char* mqtt_server ="192.168.0.125";
#define mqtt_server "broker.mqtt-dashboard.com" //192.168.0.125

/** Camera class */
WiFiClient espClient;
PubSubClient client(espClient);
unsigned long lastMsg = 0;
#define MSG_BUFFER_SIZE  (50)
char msg[MSG_BUFFER_SIZE];
int value = 0;
OV2640 cam;

/** GPIO for OTA request button */
int otaButton = 12;
/** Button class */
OneButton pushBt(otaButton, true, true);

/** Function declarations */
void enableOTA(void);
void resetDevice(void);

/** 
 * Called once after reboot/powerup
 */
void callback(char* topic, byte* payload, unsigned int length) {
  Serial.print("Message arrived [");
  Serial.print(topic);
  Serial.print("] ");
  for (int i = 0; i < length; i++) {
    Serial.print((char)payload[i]);
  }
  Serial.println();

  // Switch on the LED if an 1 was received as first character
  if ((char)payload[0] == '0') {   
    digitalWrite(12, HIGH);
    digitalWrite(4, LOW);
  } else if ((char)payload[0] == '1') { 
    digitalWrite(12, LOW);
    digitalWrite(4, HIGH);
  } else if ((char)payload[0] == '2') { 
    digitalWrite(12, HIGH);
    digitalWrite(4, HIGH);
  } else if ((char)payload[0] == '3') { 
    digitalWrite(12, HIGH);
    digitalWrite(4, HIGH);
  } else {                      //Break
    digitalWrite(12, LOW);
    digitalWrite(4, LOW); 
  } 

}

void reconnect() {
  // Loop until we're reconnected
  while (!client.connected()) {
    Serial.print("Attempting MQTT connection...");
    // Create a random client ID
    String clientId = "ESP8266Client-";
    clientId += String(random(0xffff), HEX);
    // Attempt to connect
    if (client.connect(clientId.c_str())) {
      Serial.println("connected");
      // Once connected, publish an announcement...
      client.publish("outTopic", "hello world");
      // ... and resubscribe
      client.subscribe("inTopic9907");
    } else {
      Serial.print("failed, rc=");
      Serial.print(client.state());
      Serial.println(" try again in 5 seconds");
      // Wait 5 seconds before retrying
      delay(5000);
    }
  }
}

void setup()
{
	pinMode(4, OUTPUT);
  pinMode(12, OUTPUT);
  pinMode(13, OUTPUT);
  digitalWrite(12, LOW);
  digitalWrite(13, LOW);
	// Start the serial connection
	Serial.begin(115200);

	Serial.println("\n\n##################################");
	Serial.printf("Internal Total heap %d, internal Free Heap %d\n", ESP.getHeapSize(), ESP.getFreeHeap());
	Serial.printf("SPIRam Total heap %d, SPIRam Free Heap %d\n", ESP.getPsramSize(), ESP.getFreePsram());
	Serial.printf("ChipRevision %d, Cpu Freq %d, SDK Version %s\n", ESP.getChipRevision(), ESP.getCpuFreqMHz(), ESP.getSdkVersion());
	Serial.printf("Flash Size %d, Flash Speed %d\n", ESP.getFlashChipSize(), ESP.getFlashChipSpeed());
	Serial.println("##################################\n\n");

	// Initialize the ESP32 CAM, here we use the AIthinker ESP32 CAM
	delay(100);
	cam.init(esp32cam_aithinker_config);
	delay(100);

	// Connect the WiFi
	WiFi.mode(WIFI_STA);
	WiFi.begin(ssid, password);
	while (WiFi.status() != WL_CONNECTED)
	{
		delay(500);
		Serial.print(".");
	}

	// Print information how to contact the camera server
	IPAddress ip = WiFi.localIP();
	Serial.print("\nWiFi connected with IP ");
	Serial.println(ip);
  client.setServer(mqtt_server, 1883); 
  Serial.print("\n Broker IP ");
  Serial.println(mqtt_server);
  client.setCallback(callback);
#ifdef ENABLE_RTSPSERVER
	Serial.print("Stream Link: rtsp://");
	Serial.print(ip);
	Serial.println(":8554/mjpeg/1\n");
#endif
#ifdef ENABLE_WEBSERVER
	Serial.print("Browser Stream Link: http://");
	Serial.print(ip);
	Serial.println("\n");
	Serial.print("Browser Single Picture Link: http//");
	Serial.print(ip);
	Serial.println("/jpg\n");
#endif
#ifdef ENABLE_WEBSERVER
	// Initialize the HTTP web stream server
	initWebStream();
#endif

#ifdef ENABLE_RTSPSERVER
	// Initialize the RTSP stream server
	initRTSP();
#endif

	// Attach the button functions
	pushBt.attachClick(enableOTA);
	pushBt.attachDoubleClick(resetDevice);
}

void loop()
{
	if (!client.connected()) {
    reconnect();
  }
  client.loop();
	unsigned long now = millis();
  if (now - lastMsg > 10000) {
    lastMsg = now;
    ++value;
    snprintf (msg, MSG_BUFFER_SIZE, "ping #%ld", value);
    Serial.print("Publish message: ");
    Serial.println(msg);
    client.publish("outTopic", msg);
	// Check the button
	pushBt.tick();
	if (otaStarted)
	{
		ArduinoOTA.handle();
	}
	//Nothing else to do here
	delay(100);
}
}
/**
 * Handle button single click
 */
void enableOTA(void)
{
	// If OTA is not enabled
	if (!otaStarted)
	{
		// Stop the camera servers
#ifdef ENABLE_WEBSERVER
		stopWebStream();
#endif
#ifdef ENABLE_RTSPSERVER
		stopRTSP();
#endif
		delay(100);
		Serial.println("OTA enabled");
		// Start the OTA server
		startOTA();
		otaStarted = true;
	}
	else
	{
		// If OTA was enabled
		otaStarted = false;
		// Stop the OTA server
		stopOTA();
		// Restart the camera servers
#ifdef ENABLE_WEBSERVER
		initWebStream();
#endif
#ifdef ENABLE_RTSPSERVER
		initRTSP();
#endif
	}
}

/** 
 * Handle button double click
 */
void resetDevice(void)
{
	delay(100);
	WiFi.disconnect();
	esp_restart();
}
