import json
import boto3
from datetime import datetime, timezone

# Lambda: consultar_condicoes_galpao_alexa
# Versão revisada em 09/10/2026:
# - números ditos em português ("20 graus", "20,5 graus"), sem "20.0";
# - ITU com o nome usado no TCC e com a faixa de risco (Quadro 1 do TCC);
# - tempo da última medição em minutos ou horas, com aviso se estiver antiga;
# - AMAZON.FallbackIntent e SessionEndedRequest tratados;
# - pergunta em uma frase só ("pergunte ao galpão inteligente ...") encerra
#   a sessão após responder; aberta com "abrir galpão inteligente", continua.

dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table('telemetria_galpao')

DEVICE_ID = "esp32-galpao-01"
LIMITE_DADO_ANTIGO_MIN = 30  # mesmo limite do alerta de falta de comunicação

TEXTO_AJUDA = (
    "Você pode perguntar a temperatura, a umidade, o ITU "
    "ou como está o galpão."
)


# =============================================================
# FUNÇÕES AUXILIARES
# =============================================================

def numero_falado(valor):
    """20.0 -> '20' ; 20.46 -> '20,5' (vírgula, como se fala em português)."""
    valor = round(float(valor), 1)
    if valor == int(valor):
        return str(int(valor))
    return f"{valor:.1f}".replace(".", ",")


def faixa_itu(itu):
    """Faixas do Quadro 1 do TCC (Vieira; Miszinski; Blainski, 2023)."""
    if itu <= 67:
        return "sem risco de estresse térmico"
    if itu < 72:
        return "risco pequeno de estresse térmico"
    if itu < 80:
        return "risco médio de estresse térmico"
    if itu < 90:
        return "risco alto de estresse térmico"
    return "risco muito alto de estresse térmico"


def tempo_falado(minutos):
    if minutos <= 0:
        return "agora mesmo"
    if minutos == 1:
        return "há 1 minuto"
    if minutos < 60:
        return f"há {minutos} minutos"
    horas = minutos // 60
    return "há 1 hora" if horas == 1 else f"há {horas} horas"


def resposta(texto, encerrar, reprompt=None):
    corpo = {
        "outputSpeech": {"type": "PlainText", "text": texto},
        "shouldEndSession": encerrar,
    }
    if reprompt and not encerrar:
        corpo["reprompt"] = {
            "outputSpeech": {"type": "PlainText", "text": reprompt}
        }
    return {"version": "1.0", "response": corpo}


def buscar_ultima_medicao():
    retorno = table.query(
        KeyConditionExpression='deviceId = :d',
        ExpressionAttributeValues={':d': DEVICE_ID},
        ScanIndexForward=False,
        Limit=1,
    )
    itens = retorno.get('Items') or []
    return itens[0] if itens else None


# =============================================================
# HANDLER
# =============================================================

def lambda_handler(event, context):

    print("EVENTO RECEBIDO:")
    print(json.dumps(event, ensure_ascii=False))

    request_type = event['request']['type']

    # A sessão só fica aberta depois de "abrir monitor inteligente", à espera
    # da pergunta; depois de responder, a skill sempre encerra.

    # ---------------------------------------------------------
    # SKILL ABERTA
    # ---------------------------------------------------------
    if request_type == "LaunchRequest":
        return resposta(
            "Olá! O que você deseja saber sobre o galpão?",
            encerrar=False,
            reprompt=TEXTO_AJUDA,
        )

    # ---------------------------------------------------------
    # FIM DE SESSÃO (a Alexa não aceita fala nesta resposta)
    # ---------------------------------------------------------
    if request_type == "SessionEndedRequest":
        print("SESSÃO ENCERRADA:", event['request'].get('reason'))
        return {"version": "1.0", "response": {}}

    if request_type != "IntentRequest":
        return resposta("Desculpe, não consegui processar essa solicitação.", True)

    intent_name = event['request']['intent']['name']
    print("INTENT RECEBIDA:", intent_name)

    # ---------------------------------------------------------
    # INTENTS PADRÃO DA ALEXA
    # ---------------------------------------------------------
    if intent_name in ("AMAZON.StopIntent", "AMAZON.CancelIntent",
                       "AMAZON.NavigateHomeIntent"):
        return resposta("Até mais!", True)

    if intent_name == "AMAZON.HelpIntent":
        return resposta(TEXTO_AJUDA, False, reprompt=TEXTO_AJUDA)

    if intent_name == "AMAZON.FallbackIntent":
        # Comum: o agricultor pede para ligar/desligar os ventiladores com a
        # skill aberta. O acionamento é feito pela Alexa (integração Smart
        # Life), não pela skill; por isso a skill orienta e encerra a sessão.
        return resposta(
            "Eu só consulto as condições do galpão. Para ligar ou desligar "
            "os ventiladores, chame a Alexa de novo e peça direto, "
            "por exemplo: Alexa, ligar ventiladores.",
            True,
        )

    intents_galpao = ("ConsultarTemperaturaIntent", "ConsultarUmidadeIntent",
                      "ConsultarTHIIntent", "ConsultarAmbienteIntent")
    if intent_name not in intents_galpao:
        return resposta("Não entendi a pergunta. " + TEXTO_AJUDA, False,
                        reprompt=TEXTO_AJUDA)

    # ---------------------------------------------------------
    # ÚLTIMA MEDIÇÃO
    # ---------------------------------------------------------
    try:
        item = buscar_ultima_medicao()
    except Exception as e:
        print("ERRO AO CONSULTAR DYNAMODB:", str(e))
        return resposta(
            "Desculpe, não consegui consultar os dados do galpão neste momento.",
            True,
        )

    if item is None:
        return resposta("Não encontrei dados do galpão no momento.", True)

    temperatura = numero_falado(item['temperatura'])
    umidade = numero_falado(item['umidade'])
    itu_valor = float(item['thi'])
    itu = numero_falado(itu_valor)
    risco = faixa_itu(itu_valor)

    agora = datetime.now(timezone.utc).timestamp()
    minutos = int((agora - float(item['timestamp'])) / 60)
    tempo = tempo_falado(minutos)

    aviso = ""
    if minutos > LIMITE_DADO_ANTIGO_MIN:
        aviso = (" Atenção: o sensor está sem enviar dados há algum tempo, "
                 "então essa informação pode não ser a atual.")

    if intent_name == "ConsultarTemperaturaIntent":
        fala = f"A temperatura do galpão é de {temperatura} graus."

    elif intent_name == "ConsultarUmidadeIntent":
        fala = f"A umidade do galpão é de {umidade} por cento."

    elif intent_name == "ConsultarTHIIntent":
        fala = f"O ITU do galpão é {itu}, o que indica {risco}."

    else:  # ConsultarAmbienteIntent
        fala = (f"A temperatura do galpão é de {temperatura} graus, "
                f"a umidade é de {umidade} por cento "
                f"e o ITU é {itu}, o que indica {risco}.")

    fala += f" A última medição foi realizada {tempo}.{aviso}"

    # Versão de 09/10/2026: sempre encerra após responder. Com a sessão
    # aberta, o comando seguinte ("Alexa, ligar ventiladores") ia para a
    # skill e não para a integração Smart Life (observado em teste).
    return resposta(fala, True)
