import datetime
import os
import json
from django.shortcuts import redirect, render
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from .models import MetricaSaude
from django.conf import settings # Importante para o BASE_DIR

# 1. Scope e Variável de Segurança
SCOPES = ['https://www.googleapis.com/auth/fitness.activity.read']
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

def google_fit_auth(request):
    """Inicia o login no Google"""
    os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
    client_secrets_path = os.path.join(settings.BASE_DIR, 'client_secret.json')

    flow = Flow.from_client_secrets_file(
        client_secrets_path,
        scopes=SCOPES,
        redirect_uri='http://localhost:8000/google-fit/callback/'
    )
    
    # O flow gera um 'code_verifier' automaticamente. Vamos guardá-lo!
    authorization_url, state = flow.authorization_url(prompt='consent')
    
    request.session['oauth_state'] = state
    request.session['code_verifier'] = flow.code_verifier # GUARDAR O SEGREDO
    return redirect(authorization_url)

def google_fit_callback(request):
    """Recebe o retorno do Google"""
    state = request.session.get('oauth_state')
    # BUSCAR O SEGREDO QUE GUARDÁMOS
    code_verifier = request.session.get('code_verifier') 

    client_secrets_path = os.path.join(settings.BASE_DIR, 'client_secret.json')

    flow = Flow.from_client_secrets_file(
        client_secrets_path,
        scopes=SCOPES,
        state=state,
        redirect_uri='http://localhost:8000/google-fit/callback/'
    )
    
    # USAR O SEGREDO NA VOLTA
    flow.fetch_token(
        authorization_response=request.build_absolute_uri(),
        code_verifier=code_verifier
    )

    credentials = flow.credentials

    fitness_service = build('fitness', 'v1', credentials=credentials)
    
    now = datetime.datetime.utcnow()
    start_time = now - datetime.timedelta(days=1)

    body = {
        "aggregateBy": [{"dataTypeName": "com.google.step_count.delta"}],
        "bucketByTime": {"durationMillis": 3600000},
        "startTimeMillis": int(start_time.timestamp() * 1000),
        "endTimeMillis": int(now.timestamp() * 1000)
    }

    dataset = fitness_service.users().dataset().aggregate(userId='me', body=body).execute()

    dados_para_template = []

    for bucket in dataset.get('bucket', []):
        start_ms = int(bucket['startTimeMillis'])
        dt_object = datetime.datetime.fromtimestamp(start_ms / 1000.0)

        for dataset_item in bucket.get('dataset', []):
            for point in dataset_item.get('point', []):
                passos = point['value'][0]['intVal']
                
                if passos > 0:
                    MetricaSaude.objects.update_or_create(
                        timestamp=dt_object,
                        tipo='steps',
                        defaults={'valor': passos}
                    )
                    dados_para_template.append({'hora': dt_object, 'valor': passos})

    return render(request, 'sleep_analysis/dashboard.html', {
        'passos_detalhe': dados_para_template,
        'status': 'Sincronização concluída!'
    })

def dashboard(request):
    """View para mostrar o gráfico"""
    registos = MetricaSaude.objects.filter(tipo='steps').order_by('timestamp')
    
    context = {
        'labels': json.dumps([r.timestamp.strftime("%H:%M") for r in registos]),
        'valores': json.dumps([r.valor for r in registos]),
        'registos': registos,
    }
    return render(request, 'sleep_analysis/dashboard.html', context)