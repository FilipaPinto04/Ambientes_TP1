import datetime
import os
import json
from django.shortcuts import redirect, render
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from .models import MetricaSaude
from django.conf import settings # Importante para o BASE_DIR
import requests
from google.oauth2.credentials import Credentials


# 1. Scope e Variável de Segurança
SCOPES = [
    'https://www.googleapis.com/auth/fitness.activity.read',
    'https://www.googleapis.com/auth/fitness.heart_rate.read',
    'https://www.googleapis.com/auth/fitness.sleep.read',
    'openid',
    'https://www.googleapis.com/auth/userinfo.profile',
    'https://www.googleapis.com/auth/userinfo.email',
]

os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

def home(request):
    """Página inicial com o botão de login"""
    return render(request, 'sleep_analysis/home.html')

def google_fit_auth(request):
    # 1. SE JÁ TEMOS CREDENCIAIS VÁLIDAS, SALTAMOS O LOGIN
    creds_data = request.session.get('credentials')
    if creds_data:
        creds = Credentials(**creds_data)
        if creds and creds.valid:
            # Vai direto para o callback, mas avisa que não precisa de novo token
            return redirect('google_fit_callback')

    # 2. SE NÃO TEMOS, PEDIMOS LOGIN (FLUXO NORMAL)
    client_secrets_path = os.path.join(settings.BASE_DIR, 'client_secret.json')
    flow = Flow.from_client_secrets_file(
        client_secrets_path,
        scopes=SCOPES,
        redirect_uri='http://localhost:8000/google-fit/callback/'
    )
    # prompt='select_account' em vez de 'consent' torna o login mais rápido
    authorization_url, state = flow.authorization_url(access_type='offline', prompt='select_account')
    
    request.session['oauth_state'] = state
    request.session['code_verifier'] = flow.code_verifier
    return redirect(authorization_url)

def google_fit_callback(request):
    """Recebe o retorno do Google e processa os dados de sono e perfil"""
    creds_data = request.session.get('credentials')
    credentials = None 

    # 1. TENTAR USAR CREDENCIAIS QUE JÁ ESTÃO NA SESSÃO
    if creds_data:
        from google.oauth2.credentials import Credentials
        credentials = Credentials(**creds_data)
        if not credentials.valid:
            credentials = None 

    # 2. SE NÃO TEMOS CREDENCIAIS, BUSCAMOS NOVO TOKEN
    if not credentials:
        state = request.session.get('oauth_state')
        code_verifier = request.session.get('code_verifier')
        
        flow = Flow.from_client_secrets_file(
            os.path.join(settings.BASE_DIR, 'client_secret.json'),
            scopes=SCOPES, state=state,
            redirect_uri='http://localhost:8000/google-fit/callback/'
        )
        
        try:
            flow.fetch_token(authorization_response=request.build_absolute_uri(), code_verifier=code_verifier)
            credentials = flow.credentials
            
            # GUARDAR NA SESSÃO
            request.session['credentials'] = {
                'token': credentials.token,
                'refresh_token': credentials.refresh_token,
                'token_uri': credentials.token_uri,
                'client_id': credentials.client_id,
                'client_secret': credentials.client_secret,
                'scopes': credentials.scopes
            }
        except Exception as e:
            print(f"Erro ao obter token: {e}")
            return redirect('google_fit_auth')

    # 3. BUSCAR INFORMAÇÃO DO UTILIZADOR (NOME E FOTO) - MÉTODO SEGURO
    try:
        import requests
        user_info_url = "https://www.googleapis.com/oauth2/v2/userinfo"
        headers = {'Authorization': f'Bearer {credentials.token}'}
        info_res = requests.get(user_info_url, headers=headers).json()
        
        request.session['user_name'] = info_res.get('name', 'Utilizador')
        request.session['user_picture'] = info_res.get('picture', '')
    except Exception as e:
        print(f"Erro ao buscar perfil: {e}")
        request.session['user_name'] = "Utilizador"

    # 4. CONFIGURAR SERVIÇO FITNESS E TEMPO
    fitness_service = build('fitness', 'v1', credentials=credentials)
    now = datetime.datetime.utcnow()
    start_time = now - datetime.timedelta(days=7)
    start_iso = start_time.isoformat() + 'Z'

    # --- BUSCAR SESSÕES DE SONO ---
    sessions_res = fitness_service.users().sessions().list(userId='me', startTime=start_iso).execute()
    sessoes_sono = [s for s in sessions_res.get('session', []) if s['activityType'] == 72]

    dados_agrupados = {}
    analise_list = []
    ultimo_bpm_medio = 65 

    for s in sessoes_sono:
        dia_label = datetime.datetime.fromtimestamp(int(s['startTimeMillis'])/1000).strftime("%d/%m")
        duracao_h = (int(s['endTimeMillis']) - int(s['startTimeMillis'])) / 3600000
        dados_agrupados[dia_label] = dados_agrupados.get(dia_label, 0) + duracao_h

    # Ordenar dados para o gráfico
    labels_ordenados = sorted(dados_agrupados.keys())
    valores_ordenados = [round(dados_agrupados[d], 1) for d in labels_ordenados]
    horas_hoje = valores_ordenados[-1] if valores_ordenados else 0

    # --- BUSCAR BPM DA ÚLTIMA NOITE ---
    if sessoes_sono:
        ultima = sessoes_sono[-1]
        u_start, u_end = int(ultima['startTimeMillis']), int(ultima['endTimeMillis'])
        
        body_bpm = {
            "aggregateBy": [{"dataTypeName": "com.google.heart_rate.bpm"}],
            "bucketByTime": {"durationMillis": u_end - u_start},
            "startTimeMillis": u_start, 
            "endTimeMillis": u_end
        }
        try:
            res_bpm = fitness_service.users().dataset().aggregate(userId='me', body=body_bpm).execute()
            ultimo_bpm_medio = res_bpm['bucket'][0]['dataset'][0]['point'][0]['value'][0]['fpVal']
        except:
            pass

        # Diagnóstico Lusíadas
        if horas_hoje < 7:
            analise_list.append(f"Sono insuficiente ({horas_hoje}h). Segundo especialistas, o ideal é entre 7h a 9h.")
        if ultimo_bpm_medio > 75:
            analise_list.append("BPM Elevado: Pode indicar má qualidade de sono ou stress físico.")

    # --- DADOS CLIMÁTICOS ---
    clima = get_weather_data("Braga")
    if sessoes_sono:
        fim_sono_ts = int(sessoes_sono[-1]['endTimeMillis']) / 1000
        if fim_sono_ts > clima['sunrise']:
            analise_list.append("Fator Luz: Acordou após o nascer do sol, o que pode afetar o ciclo circadiano.")

    context = {
        'labels': json.dumps(labels_ordenados),
        'valores': json.dumps(valores_ordenados),
        'horas_sono': horas_hoje,
        'bpm_medio': ultimo_bpm_medio,
        'analise': analise_list,
        'clima': clima
    }

    return render(request, 'sleep_analysis/dashboard.html', context)

def dashboard(request):
    # Procura todos os registos de sono guardados, sem limitar a apenas hoje
    registos = MetricaSaude.objects.filter(tipo='sleep').order_by('timestamp')
    
    dados_agrupados = {}
    for r in registos:
        dia = r.timestamp.strftime("%d/%m")
        # Se guardaste em minutos na DB, converte para horas
        valor_h = r.valor / 60 if r.valor > 24 else r.valor 
        dados_agrupados[dia] = dados_agrupados.get(dia, 0) + valor_h

    labels_ordenados = sorted(dados_agrupados.keys())
    valores_ordenados = [round(dados_agrupados[d], 1) for d in labels_ordenados]

    # 3. Preparar o contexto igual ao do callback
    context = {
        'labels': json.dumps(labels_ordenados),
        'valores': json.dumps(valores_ordenados),
        'horas_sono': valores_ordenados[-1] if valores_ordenados else 0,
        'bpm_medio': 65, # Valor genérico ou busca o último registo de BPM
        'analise': ["Dados carregados do histórico."],
        'clima': get_weather_data("Braga")
    }
    
    return render(request, 'sleep_analysis/dashboard.html', context)

def get_weather_data(city="Braga"):
    api_key = "cd86dc586e079435323b617b2d68184e"
    url = f"http://api.openweathermap.org/data/2.5/weather?q={city}&appid={api_key}&units=metric"
    response = requests.get(url).json()
    
    # Dentro de get_weather_data
    return {
        "temp": response['main']['temp'],
        "city": response['name'],
        "sunrise_format": datetime.datetime.fromtimestamp(response['sys']['sunrise']).strftime('%H:%M'),
        "sunrise": response['sys']['sunrise'],
        "sunset": response['sys']['sunset'],
        "description": response['weather'][0]['description']
    }

def avaliar_dia(dados, clima):

    analise = []
    
    # 1. Possível Insónia (Duração curta + BPM instável)
    horas_sono = dados['minutos_sono'] / 60
    if horas_sono < 5:
        analise.append("Sinais de Insónia: Tempo total de sono muito abaixo do recomendado. Verifique se tem dificuldade em iniciar o sono.")

    # 2. Apneia do Sono (BPM com picos ou elevado)
    # Se os batimentos médios estão altos, o corpo não descansou
    if dados['bpm_repouso'] > 75:
        analise.append("Sinais de Apneia/Stress: Frequência cardíaca elevada durante o sono. Pode indicar esforço respiratório ou sono fragmentado.")

    # 3. Síndrome das Pernas Inquietas (Detetado por pequenos picos de batimento)
    # (Lógica simplificada para o TP)
    if dados['passos'] > 500 and dados['minutos_sono'] > 0:
        analise.append("Movimentação Excessiva: Foram detetados passos durante o horário de sono. Pode indicar sonambulismo ou pernas inquietas.")

    # 4. Cruzamento Bio-Climatológico
    if dados['fim_sono'] > clima['sunrise']:
        analise.append("Atraso de Fase: Acordar após o nascer do sol desregula o cortisol matinal.")

    return analise

def doencas(request):
    """Página informativa sobre distúrbios do sono baseada nas Lusíadas"""
    return render(request, 'sleep_analysis/doencas.html')

def perfil(request):

    """Página de perfil do utilizador"""
    # Aqui podes passar o nome do utilizador ou dados de estatísticas
    return render(request, 'sleep_analysis/perfil.html')

def logout_view(request):
    request.session.flush() # Limpa tudo!
    return redirect('home')