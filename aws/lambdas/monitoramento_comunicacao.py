"""
Lambda: monitoramento_comunicacao  (Python 3.12)

Verifica se o dispositivo embarcado (esp32-galpao-01) continua enviando dados.
Disparo: Amazon EventBridge Scheduler a cada 10 minutos.

Regras:
- Se o último registro em telemetria_galpao tiver mais de LIMITE_MINUTOS
  (padrão 30 min = 3 envios perdidos) e o estado salvo for OK:
    envia ao autor "Sem comunicação..." e abre uma ocorrência (início).
- Se chegou dado novo e o estado salvo for FALHA:
    envia "Comunicação restabelecida..." e fecha a ocorrência (fim e duração).
- Nos demais casos não faz nada (evita mensagem repetida a cada 10 min).

Variáveis de ambiente (configurar no console da Lambda):
  TELEGRAM_TOKEN            token do bot (novo, gerado no BotFather)
  TELEGRAM_CHAT_ID          chat particular do AUTOR (não o grupo do agricultor)
  LIMITE_MINUTOS            opcional, padrão 30 (usar 1 só nos testes T1 a T3)
  NOME_LOCAL                opcional, ex.: "Propriedade A" (aparece na mensagem)

Tabela nova no DynamoDB: monitoramento_comunicacao
  chave de partição: id (String)   -- sem chave de ordenação
  itens:
    id = "estado#esp32-galpao-01"          -> estado atual (OK/FALHA)
    id = "falha#esp32-galpao-01#<inicio>"  -> uma ocorrência (início, fim, duração)
"""

import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key

DEVICE_ID = "esp32-galpao-01"
LIMITE_MINUTOS = int(os.environ.get("LIMITE_MINUTOS", "30"))
FUSO_BRASILIA = timezone(timedelta(hours=-3))  # Brasil sem horário de verão
NOME_LOCAL = os.environ.get("NOME_LOCAL", "").strip()
DISPOSITIVO = f"ESP32 ({NOME_LOCAL})" if NOME_LOCAL else "ESP32"

dynamodb = boto3.resource("dynamodb")
tabela_telemetria = dynamodb.Table("telemetria_galpao")
tabela_monitor = dynamodb.Table("monitoramento_comunicacao")

ID_ESTADO = f"estado#{DEVICE_ID}"


# -------------------------------------------------------------
# Auxiliares
# -------------------------------------------------------------

def hora_brasilia(ts_segundos):
    return datetime.fromtimestamp(ts_segundos, FUSO_BRASILIA).strftime("%d/%m %H:%M")


def duracao_texto(segundos):
    minutos = int(segundos // 60)
    horas, minutos = divmod(minutos, 60)
    if horas == 0:
        return f"{minutos} min"
    return f"{horas} h {minutos} min"


def enviar_telegram(texto):
    """Envia a mensagem e devolve o horário (Unix, s) informado pela API do Telegram."""
    token = os.environ["TELEGRAM_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    dados = urllib.parse.urlencode({"chat_id": chat_id, "text": texto}).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage", data=dados)
    with urllib.request.urlopen(req, timeout=10) as resp:
        corpo = json.loads(resp.read())
    if not corpo.get("ok"):
        raise RuntimeError(f"Telegram recusou a mensagem: {corpo}")
    return corpo["result"]["date"]


def ultimo_registro_ts():
    """Horário (s) do último registro do dispositivo, ou None se não houver."""
    resp = tabela_telemetria.query(
        KeyConditionExpression=Key("deviceId").eq(DEVICE_ID),
        ScanIndexForward=False,
        Limit=1,
    )
    itens = resp.get("Items") or []
    return float(itens[0]["timestamp"]) if itens else None


def ler_estado():
    item = tabela_monitor.get_item(Key={"id": ID_ESTADO}).get("Item")
    return item or {"id": ID_ESTADO, "estado": "OK"}


# -------------------------------------------------------------
# Handler
# -------------------------------------------------------------

def lambda_handler(event, context):
    agora = datetime.now(timezone.utc).timestamp()
    ultimo = ultimo_registro_ts()
    estado = ler_estado()

    sem_dados_min = None if ultimo is None else (agora - ultimo) / 60
    em_falha = ultimo is None or sem_dados_min > LIMITE_MINUTOS

    print(json.dumps({
        "ultimo_registro": ultimo,
        "minutos_sem_dados": sem_dados_min,
        "estado_salvo": estado["estado"],
        "limite_min": LIMITE_MINUTOS,
    }))

    # ---- OK -> FALHA: abre ocorrência e avisa uma única vez
    if em_falha and estado["estado"] == "OK":
        desde = "sem registro anterior" if ultimo is None else hora_brasilia(ultimo)
        texto = (f"⚠️ Sem comunicação com o {DISPOSITIVO} há mais de {LIMITE_MINUTOS} minutos. "
                 f"Último dado recebido: {desde}.")
        enviado_em = enviar_telegram(texto)

        inicio = Decimal(str(int(ultimo if ultimo is not None else agora)))
        tabela_monitor.put_item(Item={
            "id": f"falha#{DEVICE_ID}#{int(inicio)}",
            "deviceId": DEVICE_ID,
            "inicio": inicio,                    # último dado antes da falha
            "detectado_em": Decimal(str(int(agora))),
            "alerta_enviado_em": Decimal(str(enviado_em)),
        })
        tabela_monitor.put_item(Item={
            "id": ID_ESTADO,
            "estado": "FALHA",
            "ocorrencia_id": f"falha#{DEVICE_ID}#{int(inicio)}",
            "inicio": inicio,
        })
        print("FALHA registrada e alerta enviado")
        return {"status": "falha_aberta"}

    # ---- FALHA -> OK: fecha ocorrência e avisa
    if not em_falha and estado["estado"] == "FALHA":
        inicio = float(estado["inicio"])
        duracao = ultimo - inicio  # do último dado antes da falha ao primeiro depois
        texto = (f"✅ Comunicação com o {DISPOSITIVO} restabelecida às {hora_brasilia(ultimo)} "
                 f"({duracao_texto(duracao)} sem dados).")
        enviado_em = enviar_telegram(texto)

        tabela_monitor.update_item(
            Key={"id": estado["ocorrencia_id"]},
            UpdateExpression="SET fim = :f, duracao_s = :d, retorno_enviado_em = :e",
            ExpressionAttributeValues={
                ":f": Decimal(str(int(ultimo))),
                ":d": Decimal(str(int(duracao))),
                ":e": Decimal(str(enviado_em)),
            },
        )
        tabela_monitor.put_item(Item={"id": ID_ESTADO, "estado": "OK"})
        print("Ocorrência encerrada e aviso de retorno enviado")
        return {"status": "falha_encerrada"}

    print("Sem mudança de estado")
    return {"status": "sem_mudanca"}
