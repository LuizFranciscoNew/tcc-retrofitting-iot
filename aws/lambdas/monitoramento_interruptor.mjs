import crypto from "crypto";
import https from "https";
import { DynamoDBClient, PutItemCommand, ScanCommand } from "@aws-sdk/client-dynamodb";

const client = new DynamoDBClient({});

const CLIENT_ID = process.env.TUYA_CLIENT_ID;
const SECRET = process.env.TUYA_CLIENT_SECRET;
const HOST = "openapi.tuyaus.com";

// Lista dos dois dispositivos
const DEVICES = [
    { id: process.env.DEVICE_ID_VENTILADOR, switchName: "ventilador" },
    { id: process.env.DEVICE_ID_PULVERIZADOR, switchName: "pulverizador" }
];

// =========================

function sha256(content) {
    return crypto.createHash("sha256").update(content).digest("hex");
}

function sign(method, path, token = "", body = "") {
    const t = Date.now().toString();
    const contentHash = sha256(body || "");
    const stringToSign = `${method}\n${contentHash}\n\n${path}`;
    const signStr = CLIENT_ID + token + t + stringToSign;
    const sign = crypto
        .createHmac("sha256", SECRET)
        .update(signStr)
        .digest("hex")
        .toUpperCase();
    return { sign, t };
}

function request(options) {
    return new Promise((resolve, reject) => {
        const req = https.request(options, (res) => {
            let data = "";
            res.on("data", chunk => data += chunk);
            res.on("end", () => {
                try { resolve(JSON.parse(data)); }
                catch { resolve(data); }
            });
        });
        req.on("error", reject);
        req.end();
    });
}

// =========================

export const handler = async () => {
    try {
        // Obtém token uma única vez para os dois dispositivos
        console.log("🔎 Pegando token...");

        const pathToken = "/v1.0/token?grant_type=1";
        const { sign: signToken, t: t1 } = sign("GET", pathToken);

        const tokenRes = await request({
            hostname: HOST,
            path: pathToken,
            method: "GET",
            headers: {
                client_id: CLIENT_ID,
                sign: signToken,
                t: t1,
                sign_method: "HMAC-SHA256"
            }
        });

        if (!tokenRes.success) throw new Error("Erro token");

        const access_token = tokenRes.result.access_token;

        // =========================
        // Itera sobre os dois dispositivos

        for (const device of DEVICES) {
            console.log(`🔎 Verificando ${device.switchName} (${device.id})...`);

            const pathStatus = `/v1.0/devices/${device.id}/status`;
            const { sign: signStatus, t: t2 } = sign("GET", pathStatus, access_token);

            const statusRes = await request({
                hostname: HOST,
                path: pathStatus,
                method: "GET",
                headers: {
                    client_id: CLIENT_ID,
                    access_token: access_token,
                    sign: signStatus,
                    t: t2,
                    sign_method: "HMAC-SHA256"
                }
            });

            if (!statusRes.success) {
                console.error(`❌ Erro ao buscar status de ${device.switchName}`);
                continue;
            }

            const switchData = statusRes.result.find(item => item.code === "switch_1");

            if (!switchData) {
                console.error(`❌ Switch não encontrado para ${device.switchName}`);
                continue;
            }

            const currentStatus = switchData.value ? "ON" : "OFF";
            console.log(`Estado atual ${device.switchName}:`, currentStatus);

            // =========================
            // Evita duplicados — filtra por device_id

            const lastItemRes = await client.send(new ScanCommand({
                TableName: "eventos_interruptor"
            }));

            const items = (lastItemRes.Items || [])
                .filter(item => item.device_id.S === device.id)
                .sort((a, b) => Number(b.timestamp.N) - Number(a.timestamp.N));

            const lastStatus = items.length > 0 ? items[0].status.S : null;

            if (lastStatus === currentStatus) {
                console.log(`🔁 ${device.switchName} sem mudança, não salvando...`);
                continue;
            }

            // =========================
            // Salva evento

            const now = Date.now();

            await client.send(new PutItemCommand({
                TableName: "eventos_interruptor",
                Item: {
                    ID: { S: `${device.id}_${now}` },
                    device_id: { S: device.id },
                    status: { S: currentStatus },
                    switch: { S: device.switchName },
                    timestamp: { N: now.toString() }
                }
            }));

            console.log(`✅ MUDANÇA SALVA: ${device.switchName} → ${currentStatus}`);
        }

    } catch (err) {
        console.error("❌ ERRO:", JSON.stringify(err, null, 2));
    }

    return { statusCode: 200 };
};