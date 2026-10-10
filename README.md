# Protótipo de retrofitting IoT em um sistema de climatização de bovinos leiteiros

Código-fonte do protótipo desenvolvido no Trabalho de Conclusão de Curso de Engenharia de Computação (Unoesc Chapecó), consolidado neste repositório ao final do desenvolvimento.

O protótipo acrescenta ao sistema de climatização de um galpão de bovinos leiteiros (controlador MT-512E + ventiladores) monitoramento remoto da temperatura, da umidade e do Índice de Temperatura e Umidade (ITU), alertas via Telegram, consulta por voz (Amazon Alexa), *dashboard* no Grafana e acionamento remoto dos ventiladores por um interruptor inteligente ligado em paralelo (*three-way*) com o botão manual. O controlador MT-512E não é alterado.

## Arquitetura

```
SHT40 --I2C--> ESP32 --MQTT/TLS (8883)--> AWS IoT Core --regra--> lambda_telemetria_tcc --> DynamoDB telemetria_galpao
                                                                        (calcula o ITU)              |
                                                       DynamoDB Streams <-----------------------------+
                                                              |
                                                       monitoramento_thi --> Telegram (grupo de alertas)

EventBridge Scheduler (10 min) --> monitoramento_comunicacao --> Telegram (grupo de manutenção)
EventBridge Scheduler (2 min)  --> monitoramento_interruptor --> API em nuvem da Tuya --> DynamoDB eventos_interruptor
Amazon Alexa (skill "monitor inteligente") --> consultar_condicoes_galpao_alexa --> DynamoDB telemetria_galpao
Grafana Cloud (plugin DynamoDB) --> telemetria_galpao, historico_estado_galpao, eventos_interruptor
Smart Life / Alexa --> nuvem Tuya --> interruptor inteligente (acionamento; não passa pela AWS)
```

## Estrutura

| Pasta | Conteúdo |
|---|---|
| `firmware/` | `armazenar_certificados_esp.ino` (grava uma vez os certificados na NVS do ESP32) e `codigo_sensor_sht40.ino` (firmware de operação) |
| `aws/lambdas/` | Código das cinco funções AWS Lambda |
| `aws/README.md` | Tabelas do DynamoDB, variáveis de ambiente, agendamentos e regra do IoT Core |
| `alexa/` | Frases de exemplo dos intents da *skill* (CSV) |
| `grafana/` | *Dashboard* exportado em JSON (fonte de dados substituída por `DATASOURCE_DYNAMODB`) |

## Versões

| Ferramenta | Versão |
|---|---|
| Arduino IDE | 2.3.2 |
| esp32 by Espressif Systems (placa ESP32 Dev Module) | 3.3.8 |
| PubSubClient | 2.8 |
| ArduinoJson | 7.1.0 |
| Adafruit SHT4x Library / BusIO / Unified Sensor | 1.0.5 / 1.17.4 / 1.1.15 |
| AWS Lambda | Python 3.12 (telemetria, alertas, comunicação), Python 3.14 (*skill*), Node.js 24.x (interruptor) |

## O que não está no repositório

Certificados, chave privada do dispositivo, senha do Wi-Fi, endpoint do AWS IoT Core, token do bot do Telegram, identificadores de chat e credenciais da Tuya. No firmware, os valores foram substituídos por marcadores (`SEU_SSID`, `SUA_SENHA_WIFI`, `SEU_ENDPOINT`); os certificados são gravados na NVS pelo programa de provisionamento. Nas funções Lambda, os segredos ficam em variáveis de ambiente.
