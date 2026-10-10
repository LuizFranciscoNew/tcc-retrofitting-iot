import json
import boto3
import time
from decimal import Decimal

dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table('telemetria_galpao')


def calcular_thi(temperatura: float, umidade: float) -> float:
    return (1.8 * temperatura + 32) - \
           ((0.55 - (0.0055 * umidade)) * (1.8 * temperatura - 26))


def lambda_handler(event, context):

    print("Evento recebido:", event)

    deviceId = event.get('deviceId')
    temperatura_raw = event.get('temperatura')
    umidade_raw = event.get('umidade')

    if deviceId is None or temperatura_raw is None or umidade_raw is None:
        print("Payload incompleto:", event)
        return {
            'statusCode': 400,
            'body': json.dumps('Payload incompleto: deviceId, temperatura e umidade são obrigatórios')
        }

    temperatura_float = float(temperatura_raw)
    umidade_float = float(umidade_raw)

    thi_float = calcular_thi(temperatura_float, umidade_float)

    temperatura = Decimal(str(temperatura_float))
    umidade = Decimal(str(umidade_float))
    thi = Decimal(str(round(thi_float, 2)))

    timestamp = int(time.time())

    table.put_item(
        Item={
            'deviceId': deviceId,
            'timestamp': timestamp,
            'temperatura': temperatura,
            'umidade': umidade,
            'thi': thi
        }
    )

    return {
        'statusCode': 200,
        'body': json.dumps('Dados gravados')
    }
