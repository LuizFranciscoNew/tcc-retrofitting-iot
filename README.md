# Configuração na AWS (região us-east-1)

## Tabelas do Amazon DynamoDB

| Tabela | Chave de partição | Chave de classificação | Gravada por |
|---|---|---|---|
| telemetria_galpao | deviceId (String) | timestamp (Number, s) | lambda_telemetria_tcc |
| estado_alerta_galpao | deviceId (String) | - | monitoramento_thi |
| historico_estado_galpao | deviceId (String) | timestamp (Number, s) | monitoramento_thi |
| eventos_interruptor | ID (String) | - | monitoramento_interruptor (timestamp em ms) |
| monitoramento_comunicacao | id (String) | - | monitoramento_comunicacao |

DynamoDB Streams habilitado em telemetria_galpao (eventos INSERT acionam monitoramento_thi).

## Funções Lambda

| Função | Runtime | Disparo | Variáveis de ambiente |
|---|---|---|---|
| lambda_telemetria_tcc | Python 3.12 | Regra do AWS IoT Core (tópico galpao/esp32-galpao-01/telemetria) | - |
| monitoramento_thi | Python 3.12 | DynamoDB Streams (telemetria_galpao) | TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, LIMIAR_ENTRADA (80), LIMIAR_SAIDA (78) |
| monitoramento_comunicacao | Python 3.12 | EventBridge Scheduler, rate(10 minutes) | TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, LIMITE_MINUTOS (30), NOME_LOCAL |
| monitoramento_interruptor | Node.js 24.x | EventBridge Scheduler, a cada 2 min | TUYA_CLIENT_ID, TUYA_CLIENT_SECRET, DEVICE_ID_VENTILADOR, DEVICE_ID_PULVERIZADOR |
| consultar_condicoes_galpao_alexa | Python 3.14 | Alexa Skills Kit | - |

## Regra do AWS IoT Core

Encaminha as mensagens do tópico `galpao/esp32-galpao-01/telemetria` para a lambda_telemetria_tcc (ação: AWS Lambda).

```sql
SELECT * FROM 'galpao/esp32-galpao-01/telemetria'
```

A mensagem JSON publicada pelo ESP32 é repassada inteira à função, que lê `deviceId`, `temperatura` e `umidade` e recalcula o ITU (o campo `thi` enviado pelo firmware é ignorado).

## Permissões

A função monitoramento_comunicacao tem permissão apenas para Query em telemetria_galpao e GetItem, PutItem e UpdateItem em monitoramento_comunicacao (política em linha com menor privilégio).
