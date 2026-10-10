#include <Preferences.h>

Preferences preferences;

const char* root_ca = R"EOF(
-----BEGIN CERTIFICATE-----
(Amazon Root CA 1)
-----END CERTIFICATE-----
)EOF";

const char* device_cert = R"KEY(
-----BEGIN CERTIFICATE-----
(certificado do dispositivo gerado no AWS IoT Core - NÃO publicar)
-----END CERTIFICATE-----
)KEY";

const char* private_key = R"KEY(
-----BEGIN RSA PRIVATE KEY-----
(chave privada do dispositivo - NÃO publicar)
-----END RSA PRIVATE KEY-----
)KEY";

void setup() {

  Serial.begin(115200);
  delay(2000);

  Serial.println("=== Provisionamento AWS IoT ===");

  preferences.begin("aws", false);

  Serial.println("Salvando Root CA...");
  preferences.putString("rootCA", root_ca);

  Serial.println("Salvando Device Certificate...");
  preferences.putString("deviceCert", device_cert);

  Serial.println("Salvando Private Key...");
  preferences.putString("privKey", private_key);

  preferences.end();

  Serial.println("Certificados gravados com sucesso!");
  Serial.println("Agora você pode carregar o firmware principal.");

}

void loop() {
}