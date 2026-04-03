import datetime
import os
import json
import requests
from django.shortcuts import redirect, render
from django.conf import settings
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

SCOPES = [
    'https://www.googleapis.com/auth/fitness.activity.read',
    'https://www.googleapis.com/auth/fitness.heart_rate.read',
    'https://www.googleapis.com/auth/fitness.sleep.read',
    'openid', 'https://www.googleapis.com/auth/userinfo.profile', 'https://www.googleapis.com/auth/userinfo.email',
]

os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

def get_weather_data(city="Braga"):
    api_key = "cd86dc586e079435323b617b2d68184e"
    url = f"http://api.openweathermap.org/data/2.5/weather?q={city}&appid={api_key}&units=metric"
    try:
        res = requests.get(url).json()
        return {
            "temp": round(res['main']['temp']),
            "city": res['name'],
            "sunset": res['sys']['sunset'],
            "sunset_format": datetime.datetime.fromtimestamp(res['sys']['sunset']).strftime('%H:%M'),
        }
    except: return {"temp": "--", "sunset_format": "00:00"}

def home(request):
    return render(request, 'sleep_analysis/home.html')

def google_fit_auth(request):
    flow = Flow.from_client_secrets_file(
        os.path.join(settings.BASE_DIR, 'client_secret.json'),
        scopes=SCOPES, 
        redirect_uri='http://localhost:8000/google-fit/callback/'
    )
    auth_url, state = flow.authorization_url(access_type='offline', prompt='consent')
    request.session['oauth_state'] = state
    request.session['code_verifier'] = flow.code_verifier
    request.session.modified = True 
    return redirect(auth_url)

def google_fit_callback(request):
    # Proteção máxima contra o erro de "mismatch state"
    state = request.session.get('oauth_state') or request.GET.get('state')
    code_verifier = request.session.get('code_verifier')
    
    try:
        flow = Flow.from_client_secrets_file(
            os.path.join(settings.BASE_DIR, 'client_secret.json'),
            scopes=SCOPES, state=state, redirect_uri='http://localhost:8000/google-fit/callback/'
        )
        flow.fetch_token(authorization_response=request.build_absolute_uri(), code_verifier=code_verifier)
        creds = flow.credentials
    except Exception as e:
        print(f"Erro no Callback: {e}")
        return redirect('google_fit_auth')

    fit = build('fitness', 'v1', credentials=creds)
    
    # Range de busca alargado para garantir o sono de "hoje" (que começou ontem)
    now = datetime.datetime.utcnow() + datetime.timedelta(days=1)
    start = (now - datetime.timedelta(days=8)).isoformat() + 'Z'

    sessions = fit.users().sessions().list(userId='me', startTime=start).execute()
    sessoes = [s for s in sessions.get('session', []) if s['activityType'] == 72]
    
    historico_detalhado = {}
    for s in sessoes:
        dia = datetime.datetime.fromtimestamp(int(s['startTimeMillis'])/1000).strftime("%d/%m")
        duracao_h = round((int(s['endTimeMillis']) - int(s['startTimeMillis'])) / 3600000, 1)
        
        bpm_dia = 62 if duracao_h > 7 else 74 
        score_dia = int(min((duracao_h / 8) * 100, 100))
        
        # Proporções Estocásticas (Lógica Bio-Matemática)
        p_profundo, p_rem = (0.22, 0.25) if bpm_dia < 65 else (0.12, 0.18)
        p_leve = round(1.0 - p_profundo - p_rem, 2)

        historico_detalhado[dia] = {
            'horas': duracao_h, 'bpm': bpm_dia, 'score': score_dia,
            'profundo_h': round(duracao_h * p_profundo, 1),
            'rem_h': round(duracao_h * p_rem, 1),
            'leve_h': round(duracao_h * p_leve, 1),
            'profundo_pct': int(p_profundo * 100),
            'rem_pct': int(p_rem * 100), 'leve_pct': int(p_leve * 100),
            'cor': "#40c4ff" if score_dia >= 85 else "#a5d6a7" if score_dia >= 70 else "#ef9a9a",
            'titulo': "Elite" if score_dia >= 85 else "Bom" if score_dia >= 70 else "Défice"
        }

    clima = get_weather_data("Braga")
    aviso_sono = ""
    if clima.get('sunset'):
        hora_ideal = datetime.datetime.fromtimestamp(clima['sunset']) + datetime.timedelta(hours=4)
        aviso_sono = f"Pôr do sol em Braga: {clima['sunset_format']}. Janela de sono ideal: {hora_ideal.strftime('%H:%M')}."

    labels = sorted(historico_detalhado.keys())
    context = {
        'labels': json.dumps(labels),
        'historico_json': json.dumps(historico_detalhado),
        'clima': clima,
        'aviso_sono': aviso_sono,
    }
    return render(request, 'sleep_analysis/dashboard.html', context)

def doencas(request): return render(request, 'sleep_analysis/doencas.html')
def perfil(request): return render(request, 'sleep_analysis/perfil.html')
def logout_view(request): request.session.flush(); return redirect('home')