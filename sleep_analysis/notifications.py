import requests

def disparar_alerta_adafruit():
    """Atuação: Envia o sinal para a nuvem Adafruit IO."""
    ADAFRUIT_USERNAME = "ambientes_inteligentes_tp1"
    ADAFRUIT_AIO_KEY = "aio_kFqb95FpswUZSZQ66rNoXZXnEffJ"
    FEED_NAME = "sensorfeed"

    url = f"https://io.adafruit.com/api/v2/{ADAFRUIT_USERNAME}/feeds/{FEED_NAME}/data"
    headers = {"X-AIO-Key": ADAFRUIT_AIO_KEY}
    payload = {"value": "1"}

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=5)
        if response.status_code == 200:
            print("Atuação: Sinal enviado para Adafruit IO!")
        else:
            print(f"Erro Adafruit: {response.status_code}")
    except Exception as e:
        print(f"Erro de rede: {e}")

def verificar_ritmo_e_notificar(regularity_data, request):
    """
    Reasoning: Só dispara se a hora de deitar de ontem 
    for 2h ou mais tarde que a média da semana.
    """
    if not regularity_data or len(regularity_data) < 2:
        print(" Dados insuficientes para calcular desvio de ritmo.")
        return

    noites_anteriores = regularity_data[:-1]
    soma_deitar = sum(noite['sleep'] for noite in noites_anteriores)
    media_deitar = soma_deitar / len(noites_anteriores)

    ontem_deitar = regularity_data[-1]['sleep']

    desvio = ontem_deitar - media_deitar

    print(f"Reasoning: Média: {media_deitar:.2f}h | Ontem: {ontem_deitar:.2f}h | Desvio: {desvio:.2f}h")

    if desvio >= 1.0:
        if not request.session.get('alerta_enviado'):
            print("ALERTA: Desvio de 1h detetado! A disparar atuação...")
            disparar_alerta_adafruit()
            request.session['alerta_enviado'] = True
    else:
        print("Ritmo estável (desvio inferior a 1h).")