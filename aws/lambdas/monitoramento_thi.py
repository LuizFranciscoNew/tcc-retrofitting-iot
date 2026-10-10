"""
Lambda: monitoramento_thi  (Python)  -- versão revisada em 09/10/2026

Disparo: DynamoDB Streams da tabela telemetria_galpao (eventos INSERT).

O que mudou em relação à versão anterior:
1. Token e chat do Telegram em VARIÁVEIS DE AMBIENTE (não ficam mais no código).
2. Histerese: entra em ALTO com ITU >= 80 (início do risco alto no Quadro 1)
   e só volta a NORMAL quando o ITU cai abaixo de 78. Evita vários alertas
   seguidos quando o ITU oscila em torno de 80 (como em 27/09 e 07/10).
3. Mensagens com "ITU" (e não "THI"), faixa de risco e recomendação curta
   (base: Daltro et al., 2020; ver seção 2.1.2 do TCC).
4. Envio para o GRUPO do Telegram (autor + agricultor).
5. Para o E2, o histórico grava também o horário do registro que disparou
   o alerta e o horário de envio devolvido pela API do Telegram.
6. Se o Telegram falhar, o erro é registrado no histórico (telegram_ok = False)
   em vez de o alerta sumir sem rastro.

Nomes internos mantidos: atributo "thi", tabelas e nome da função.
Os estados gravados continuam "ALTO" e "NORMAL" (o Grafana já usa esses valores).

Variáveis de ambiente:
  TELEGRAM_TOKEN     token do bot (gerar um novo no BotFather)
  TELEGRAM_CHAT_ID   chat_id do GRUPO (autor + agricultor); começa com "-"
  LIMIAR_ENTRADA     opcional, padrão 80
  LIMIAR_SAIDA       opcional, padrão 78
"""

import json
import os
import time
import urllib.request
from decimal import Decimal

import boto3

LIMIAR_ENTRADA = float(os.environ.get("LIMIAR_ENTRADA", "80"))
LIMIAR_SAIDA = float(os.environ.get("LIMIAR_SAIDA", "78"))

dynamodb = boto3.resource("dynamodb")
tabela_estado = dynamodb.Table("estado_alerta_galpao")
tabela_historico = dynamodb.Table("historico_estado_galpao")


# -------------------------------------------------------------
# Auxiliares
# -------------------------------------------------------------

def num(valor):
    """80.0 -> '80' ; 80.46 -> '80,5' (formato brasileiro)."""
    valor = round(float(valor), 1)
    if valor == int(valor):
        return str(int(valor))
    return f"{valor:.1f}".replace(".", ",")


def faixa_risco(itu):
    """Faixas do Quadro 1 do TCC (Vieira; Miszinski; Blainski, 2023)."""
    if itu <= 67:
        return "sem risco"
    if itu < 72:
        return "risco pequeno"
    if itu < 80:
        return "risco médio"
    if itu < 90:
        return "risco alto"
    return "risco muito alto"


def novo_estado(itu, estado_atual):
    """Histerese: entra com ITU >= 80; sai só com ITU < 78."""
    if estado_atual == "ALTO":
        return "NORMAL" if itu < LIMIAR_SAIDA else "ALTO"
    return "ALTO" if itu >= LIMIAR_ENTRADA else "NORMAL"


def mensagem_alerta(itu, temperatura, umidade):
    faixa = faixa_risco(itu)
    if itu >= 90:
        recomendacao = "Ligue os ventiladores agora e confira os animais."
    else:
        recomendacao = "Verifique se os ventiladores estão ligados e se os animais têm sombra."
    return (
        f"🚨 ITU {num(itu)}: {faixa} de estresse térmico no galpão\n\n"
        f"🌡 Temperatura: {num(temperatura)} °C\n"
        f"💧 Umidade: {num(umidade)}%\n\n"
        f"👉 {recomendacao}"
    )


def mensagem_normal(itu, temperatura, umidade, minutos_em_risco):
    duracao = ""
    if minutos_em_risco is not None:
        h, m = divmod(int(minutos_em_risco), 60)
        duracao = f"\n⏱ Tempo em risco alto: {h} h {m} min" if h else f"\n⏱ Tempo em risco alto: {m} min"
    return (
        f"✅ ITU {num(itu)}: voltou abaixo do risco alto\n\n"
        f"🌡 Temperatura: {num(temperatura)} °C\n"
        f"💧 Umidade: {num(umidade)}%"
        f"{duracao}"
    )


def enviar_telegram(texto):
    """Envia ao grupo. Devolve (ok, horário de envio informado pela API, em s)."""
    token = os.environ["TELEGRAM_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    dados = json.dumps({"chat_id": chat_id, "text": texto}).encode("utf-8")
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=dados, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            corpo = json.loads(resp.read())
        if corpo.get("ok"):
            return True, int(corpo["result"]["date"])
        print("Telegram recusou:", corpo)
    except Exception as e:  # sem internet, token inválido etc.
        print("Erro ao enviar ao Telegram:", repr(e))
    return False, None


# -------------------------------------------------------------
# Handler
# -------------------------------------------------------------

def lambda_handler(event, context):

    print("Evento:", json.dumps(event))

    for record in event["Records"]:
        if record["eventName"] != "INSERT":
            continue

        img = record["dynamodb"]["NewImage"]
        device_id = img["deviceId"]["S"]
        itu = float(img["thi"]["N"])
        temperatura = float(img.get("temperatura", {}).get("N", 0))
        umidade = float(img.get("umidade", {}).get("N", 0))
        registro_ts = int(float(img.get("timestamp", {}).get("N", time.time())))

        atual = tabela_estado.get_item(Key={"deviceId": device_id}).get("Item", {})
        estado_atual = atual.get("estado", "DESCONHECIDO")
        estado = novo_estado(itu, estado_atual)

        print(f"ITU {itu} | estado atual: {estado_atual} | novo: {estado}")

        if estado == estado_atual:
            continue

        # Primeira execução (sem estado salvo) e ITU normal: só grava, sem mensagem.
        if estado_atual == "DESCONHECIDO" and estado == "NORMAL":
            tabela_estado.put_item(Item={"deviceId": device_id, "estado": "NORMAL",
                                         "ultimo_alerta": int(time.time())})
            continue

        agora = int(time.time())

        if estado == "ALTO":
            texto = mensagem_alerta(itu, temperatura, umidade)
        else:
            inicio = atual.get("ultimo_alerta")
            minutos = (registro_ts - int(inicio)) / 60 if inicio is not None else None
            texto = mensagem_normal(itu, temperatura, umidade, minutos)

        ok, enviado_em = enviar_telegram(texto)

        tabela_estado.put_item(Item={
            "deviceId": device_id,
            "estado": estado,
            "ultimo_alerta": registro_ts,
        })

        historico = {
            "deviceId": device_id,
            "timestamp": agora,                 # mantido como antes (usado no Grafana)
            "estado": estado,
            "thi": Decimal(str(itu)),
            "registro_timestamp": registro_ts,  # E2: horário do registro que disparou
            "telegram_ok": ok,
        }
        if enviado_em is not None:
            historico["telegram_enviado_em"] = enviado_em  # E2: horário de envio (API)
        tabela_historico.put_item(Item=historico)

    return {"statusCode": 200}
