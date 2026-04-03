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
    # Força a limpeza para não haver conflitos de 'state' antigo
    request.session.flush() 
    
    client_secrets_path = os.path.join(settings.BASE_DIR, 'client_secret.json')
    
    flow = Flow.from_client_secrets_file(
        client_secrets_path,
        scopes=SCOPES,
        redirect_uri='http://127.0.0.1:8000/google-fit/callback/' # Usa 127.0.0.1 como no teu print!
    )

    authorization_url, state = flow.authorization_url(
        access_type='offline',
        prompt='consent'
    )

    request.session['oauth_state'] = state
    # Guarda o verifier, caso contrário o callback não consegue validar o código
    request.session['code_verifier'] = flow.code_verifier
    
    return redirect(authorization_url)

def google_fit_callback(request):
    # Se chegamos aqui sem o 'state', o user tentou entrar direto na URL. Manda para a Home.
    state = request.session.get('oauth_state')
    if not state:
        return redirect('home')

    client_secrets_path = os.path.join(settings.BASE_DIR, 'client_secret.json')
    flow = Flow.from_client_secrets_file(
        client_secrets_path,
        scopes=SCOPES,
        state=state,
        redirect_uri='http://127.0.0.1:8000/google-fit/callback/'
    )

    try:
        flow.fetch_token(
            authorization_response=request.build_absolute_uri(),
            code_verifier=request.session.get('code_verifier')
        )
        
        # Se chegou aqui, o login FOI UM SUCESSO.
        credentials = flow.credentials
        request.session['credentials'] = {
            'token': credentials.token,
            'refresh_token': credentials.refresh_token,
            'token_uri': credentials.token_uri,
            'client_id': credentials.client_id,
            'client_secret': credentials.client_secret,
            'scopes': credentials.scopes
        }
        return redirect('dashboard') # Vai para a página de dados final

    except Exception as e:
        print(f"ERRO CRÍTICO: {e}")
        # MANDA PARA A HOME COM ERRO, NÃO PARA O LOGIN (isso quebra o loop)
        return render(request, 'sleep_analysis/home.html', {"erro": "Falha na autenticação Google."})

def buscar_dados_e_renderizar(request, credentials):
    """Função auxiliar para processar o sono, perfil e clima"""
    from googleapiclient.discovery import build
    import requests
    import datetime
    import json

    # 1. Perfil (Nome e Foto)
    try:
        headers = {'Authorization': f'Bearer {credentials.token}'}
        info = requests.get("https://www.googleapis.com/oauth2/v2/userinfo", headers=headers).json()
        request.session['user_name'] = info.get('name', 'Utilizador')
        request.session['user_picture'] = info.get('picture', '')
    except:
        request.session['user_name'] = "Utilizador"

    # 2. Google Fit (Sono e BPM)
    fitness_service = build('fitness', 'v1', credentials=credentials)
    now = datetime.datetime.utcnow()
    start_iso = (now - datetime.timedelta(days=7)).isoformat() + 'Z'

    sessions_res = fitness_service.users().sessions().list(userId='me', startTime=start_iso).execute()
    sessoes_sono = [s for s in sessions_res.get('session', []) if s['activityType'] == 72]

    dados_agrupados = {}
    analise_list = []
    ultimo_bpm_medio = 65

    for s in sessoes_sono:
        dia = datetime.datetime.fromtimestamp(int(s['startTimeMillis'])/1000).strftime("%d/%m")
        duracao = (int(s['endTimeMillis']) - int(s['startTimeMillis'])) / 3600000
        dados_agrupados[dia] = dados_agrupados.get(dia, 0) + duracao

    labels = sorted(dados_agrupados.keys())
    valores = [round(dados_agrupados[d], 1) for d in labels]
    horas_hoje = valores[-1] if valores else 0

    if sessoes_sono:
        ultima = sessoes_sono[-1]
        u_start, u_end = int(ultima['startTimeMillis']), int(ultima['endTimeMillis'])
        body = {
            "aggregateBy": [{"dataTypeName": "com.google.heart_rate.bpm"}],
            "bucketByTime": {"durationMillis": u_end - u_start},
            "startTimeMillis": u_start, "endTimeMillis": u_end
        }
        try:
            res_bpm = fitness_service.users().dataset().aggregate(userId='me', body=body).execute()
            ultimo_bpm_medio = res_bpm['bucket'][0]['dataset'][0]['point'][0]['value'][0]['fpVal']
        except: pass

        if horas_hoje < 7: analise_list.append(f"Sono insuficiente ({horas_hoje}h).")
        if ultimo_bpm_medio > 75: analise_list.append("BPM Elevado detetado.")

    # 3. Clima
    from .views import get_weather_data # Garante que importa a tua função do clima
    clima = get_weather_data("Braga")

    context = {
        'labels': json.dumps(labels),
        'valores': json.dumps(valores),
        'horas_sono': horas_hoje,
        'bpm_medio': round(ultimo_bpm_medio, 1),
        'analise': analise_list,
        'clima': clima
    }
    return render(request, 'sleep_analysis/dashboard.html', context)

def dashboard(request):
    # 1. Verificar se temos credenciais na sessão
    creds_data = request.session.get('credentials')
    
    if not creds_data:
        # Se não há credenciais, interrompe o loop e manda para o login
        return redirect('google_fit_auth')

    try:
        # 2. Reconstruir as credenciais para usar a API
        credentials = Credentials(**creds_data)
        
        # 3. Chamar a função que vai ao Google buscar o que falta
        # e renderizar o template
        return buscar_dados_e_renderizar(request, credentials)
        
    except Exception as e:
        print(f"Erro no dashboard: {e}")
        return redirect('google_fit_auth')

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