#include <Wire.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <Preferences.h>
#include "Adafruit_SHT4x.h"

// Credenciais removidas da versão publicada (preencher antes de gravar)
const char* ssid = "SEU_SSID";
const char* password = "SUA_SENHA_WIFI";

const char* mqtt_server = "SEU_ENDPOINT-ats.iot.us-east-1.amazonaws.com";
const int mqtt_port = 8883;

WiFiClientSecure net;
PubSubClient client(net);

Adafruit_SHT4x sht4 = Adafruit_SHT4x();
Preferences preferences;

String rootCA;
String deviceCert;
String privateKey;

float somaTemperatura = 0;
float somaUmidade = 0;

float ultimaTemperatura = NAN;
float ultimaUmidade = NAN;

int contadorLeituras = 0;
int leiturasDescartadas = 0;

unsigned long tempoUltimaLeitura = 0;

const int intervaloLeitura = 10000;
const int totalLeituras = 60;

int falhasWiFi = 0;
const int limiteFalhasWiFi = 5;

void carregarCertificados() {

  preferences.begin("aws", true);

  rootCA = preferences.getString("rootCA", "");
  deviceCert = preferences.getString("deviceCert", "");
  privateKey = preferences.getString("privKey", "");

  preferences.end();

  if(rootCA == "" || deviceCert == "" || privateKey == ""){
    Serial.println("ERRO: Certificados não encontrados na NVS!");
    while(true);
  }

  Serial.println("Certificados carregados da NVS!");
}

float calcularTHI(float temperatura, float umidade) {

  float thi = (1.8 * temperatura + 32) -
              ((0.55 - (0.0055 * umidade)) * (1.8 * temperatura - 26));

  return thi;
}

void conectarWiFi() {

  Serial.println("Conectando ao WiFi...");

  WiFi.disconnect(true);
  delay(1000);

  WiFi.begin(ssid, password);

  int tentativas = 0;

  while (WiFi.status() != WL_CONNECTED) {

    delay(500);
    Serial.print(".");

    tentativas++;

    if (tentativas > 30) {
      Serial.println("\nFalha ao conectar WiFi.");
      return;
    }
  }

  Serial.println("\nWiFi conectado!");
  Serial.print("IP: ");
  Serial.println(WiFi.localIP());
}

void conectarAWS() {

  int tentativas = 0;

  while (!client.connected()) {

    Serial.print("Conectando AWS IoT...");

    if (client.connect("esp32-galpao-01")) {

      Serial.println("Conectado!");

    } else {

      Serial.print("Erro rc=");
      Serial.println(client.state());

      delay(2000);
      tentativas++;

      if (tentativas > 10) {
        Serial.println("Falha AWS. Reiniciando...");
        ESP.restart();
      }
    }
  }
}

void setup() {

  Serial.begin(115200);
  delay(1000);

  Serial.println("Boot ESP32");

  Wire.begin(21,22);

  if (!sht4.begin()) {
    Serial.println("Sensor SHT40 não encontrado!");
    ESP.restart();
  }

  carregarCertificados();

  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  WiFi.persistent(true);

  conectarWiFi();

  net.setCACert(rootCA.c_str());
  net.setCertificate(deviceCert.c_str());
  net.setPrivateKey(privateKey.c_str());

  client.setServer(mqtt_server, mqtt_port);

  conectarAWS();
}

void loop() {

  // MONITORAMENTO WIFI
  if (WiFi.status() != WL_CONNECTED) {

    Serial.println("WiFi desconectado! Tentando reconectar...");

    falhasWiFi++;

    if (falhasWiFi >= limiteFalhasWiFi) {

      Serial.println("Muitas falhas WiFi. Reiniciando ESP...");
      ESP.restart();
    }

    conectarWiFi();

  } else {

    falhasWiFi = 0;
  }

  // MONITORAMENTO MQTT
  if (!client.connected()) {
    Serial.println("MQTT desconectado!");
    conectarAWS();
  }

  client.loop();

  if (millis() - tempoUltimaLeitura >= intervaloLeitura) {

    tempoUltimaLeitura = millis();

    sensors_event_t humidity, temp;

    if (!sht4.getEvent(&humidity, &temp)) {
      Serial.println("Erro leitura SHT40");
      return;
    }

    float temperatura = temp.temperature;
    float umidade = humidity.relative_humidity;

    if(temperatura < 0 || temperatura > 50){
      Serial.print("Temperatura fora limite: ");
      Serial.println(temperatura);
      return;
    }

    if(umidade < 20 || umidade > 100){
      Serial.print("Umidade fora limite: ");
      Serial.println(umidade);
      return;
    }

    if(!isnan(ultimaTemperatura)){

      if(abs(temperatura - ultimaTemperatura) > 4){
        Serial.println("Pico anormal temperatura. Ignorado.");
        return;
      }

      if(abs(umidade - ultimaUmidade) > 30){
        Serial.println("Pico anormal umidade. Ignorado.");
        return;
      }
    }

    ultimaTemperatura = temperatura;
    ultimaUmidade = umidade;

    Serial.print("Leitura: ");
    Serial.print(temperatura);
    Serial.print(" °C | ");
    Serial.print(umidade);
    Serial.println(" %");

    if (leiturasDescartadas < 2) {

      leiturasDescartadas++;

      Serial.println("Leitura descartada (estabilização sensor)");

      return;
    }

    somaTemperatura += temperatura;
    somaUmidade += umidade;

    contadorLeituras++;

    Serial.print("Leituras válidas: ");
    Serial.println(contadorLeituras);

    if (contadorLeituras >= (totalLeituras - 2)) {

      float mediaTemp = somaTemperatura / contadorLeituras;
      float mediaUmid = somaUmidade / contadorLeituras;

      float thi = calcularTHI(mediaTemp, mediaUmid);

      Serial.println("----- MÉDIA 10 MIN -----");

      StaticJsonDocument<256> doc;

      doc["deviceId"] = "esp32-galpao-01";
      doc["temperatura"] = mediaTemp;
      doc["umidade"] = mediaUmid;
      doc["thi"] = thi;

      char jsonBuffer[256];
      serializeJson(doc, jsonBuffer);

      bool enviado = client.publish("galpao/esp32-galpao-01/telemetria", jsonBuffer);

      if(enviado){
        Serial.println("Dados enviados para AWS!");
      } else {
        Serial.println("Falha envio MQTT!");
      }

      Serial.println(jsonBuffer);

      somaTemperatura = 0;
      somaUmidade = 0;

      contadorLeituras = 0;
      leiturasDescartadas = 0;

      Serial.println("Novo ciclo iniciado...");
    }
  }
}