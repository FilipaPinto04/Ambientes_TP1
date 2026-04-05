import requests


def disparar_alerta_ifttt():
    """Envia o trigger para o Webhook do IFTTT."""
    # CHAVE CORRIGIDA: Troquei o número 1 pela letra l minúscula
    ifttt_key = "mVMNgkV2Uemn6GARDbRYgyTkApH0kfKuWl0Bgq85e5O"
    event_name = "desvio_ritmo" 
    
    url = f"https://maker.ifttt.com/trigger/{event_name}/with/key/{ifttt_key}"
    
    try:
        response = requests.post(url, timeout=5)
        if response.status_code == 200:
            print("🚀 Notificação IFTTT enviada com sucesso!")
        else:
            print(f"❌ Erro IFTTT: {response.text}")
    except Exception as e:
        print(f"⚠️ Erro de rede: {e}")

def verificar_ritmo_e_notificar(regularity_data, request):
    """Analisa os dados e decide se dispara o alerta."""
    if len(regularity_data) < 2:
        return

    noite_ontem = regularity_data[-1]
    deitar_anteriores = [d['sleep'] for d in regularity_data[:-1]]
    
    deitar_ajustado = [(h + 24 if h < 12 else h) for h in deitar_anteriores]
    media_deitar_semanal = sum(deitar_ajustado) / len(deitar_ajustado)
    
    hora_ontem = noite_ontem['sleep']
    if hora_ontem < 12: 
        hora_ontem += 24
        
    desvio_ritmo = hora_ontem - media_deitar_semanal
    
    if desvio_ritmo >= 2 and not request.session.get('notif_enviada'):
        disparar_alerta_ifttt()
        request.session['notif_enviada'] = True