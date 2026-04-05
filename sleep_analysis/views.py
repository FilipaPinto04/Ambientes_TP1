import datetime
import os
import json
import requests
import pytz
from django.shortcuts import redirect, render
from django.conf import settings
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
from googleapiclient.discovery import build
from collections import defaultdict
from .notifications import verificar_ritmo_e_notificar

# CONFIGURAÇÕES GLOBAIS

SCOPES = [
    'https://www.googleapis.com/auth/fitness.activity.read',
    'https://www.googleapis.com/auth/fitness.heart_rate.read',
    'https://www.googleapis.com/auth/fitness.sleep.read',
    'https://www.googleapis.com/auth/fitness.location.read',
    'openid',
    'https://www.googleapis.com/auth/userinfo.profile',
    'https://www.googleapis.com/auth/userinfo.email',
]

LOCAL_TZ = pytz.timezone('Europe/Lisbon')

DIAS_PT = {
    'Mon': 'Seg', 'Tue': 'Ter', 'Wed': 'Qua',
    'Thu': 'Qui', 'Fri': 'Sex', 'Sat': 'Sáb', 'Sun': 'Dom'
}

DIAS_SEMANA_PT = {
    'Monday': 'Segunda', 'Tuesday': 'Terça',  'Wednesday': 'Quarta',
    'Thursday': 'Quinta', 'Friday': 'Sexta', 'Saturday': 'Sábado', 'Sunday': 'Domingo'
}

MESES_PT = {
    'January': 'Janeiro',   'February': 'Fevereiro', 'March': 'Março',
    'April':   'Abril',     'May': 'Maio',            'June': 'Junho',
    'July':    'Julho',     'August': 'Agosto',       'September': 'Setembro',
    'October': 'Outubro',   'November': 'Novembro',   'December': 'Dezembro'
}

FASE_LABELS = {
    1: 'light',  # Acordado breve
    2: 'light',  # Sono genérico
    3: 'light',  # Sono leve padrão
    4: 'light',  # Leve 
    5: 'rem',    # REM
    6: 'deep',   # Sono profundo 
}

FASES_SONO_VALIDAS = {0, 2, 3, 4, 5, 6}

os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'


# GOOGLE FIT

class GoogleFitService:
    def __init__(self, credentials):
        self.service = build('fitness', 'v1', credentials=credentials)

    def fetch_last_location(self):
        """Devolve (lat, lon) do último ponto de localização disponível."""
        ds_id    = "derived:com.google.location.sample:com.google.android.gms:merge_location_samples"
        now_ns   = int(datetime.datetime.utcnow().timestamp() * 1e9)
        start_ns = int(now_ns - (86400 * 1e9))
        try:
            res = self.service.users().dataSources().datasets().get(
                userId='me',
                dataSourceId=ds_id,
                datasetId=f"{start_ns}-{now_ns}"
            ).execute()
            if res.get('point'):
                p = res['point'][-1]
                return p['value'][0]['fpVal'], p['value'][1]['fpVal']
        except Exception:
            pass
        return None, None


# FUNÇÕES AUXILIARES — EXTRAÇÃO DE DADOS

def buscar_bpm_detalhado(fit_service, start_ms, end_ms):
    """Devolve lista de todos os valores de BPM no intervalo dado."""
    ds_id      = "derived:com.google.heart_rate.bpm:com.google.android.gms:merge_heart_rate_bpm"
    dataset_id = f"{start_ms * 1_000_000}-{end_ms * 1_000_000}"
    try:
        res = fit_service.users().dataSources().datasets().get(
            userId='me', dataSourceId=ds_id, datasetId=dataset_id
        ).execute()
        return [p['value'][0]['fpVal'] for p in res.get('point', [])]
    except Exception:
        return []


def buscar_passos_agregados(fit_service, start_ms, end_ms):
    """Devolve buckets diários com o total de passos."""
    body = {
        "aggregateBy":     [{"dataTypeName": "com.google.step_count.delta"}],
        "bucketByTime":    {"durationMillis": 86_400_000},
        "startTimeMillis": start_ms,
        "endTimeMillis":   end_ms,
    }
    try:
        res = fit_service.users().dataset().aggregate(userId='me', body=body).execute()
        return res.get('bucket', [])
    except Exception:
        return []


def buscar_duracao_real_sono(fit_service, sessoes_sono, local_tz):
    """
    Para cada sessão, soma apenas as fases de sono reais (exclui vigília).
    Devolve dict {sessao_id: horas}.
    """
    ds_id                   = "derived:com.google.sleep.segment:com.google.android.gms:merged"
    duracao_real_por_sessao = {}

    for s in sessoes_sono:
        start_ms   = int(s['startTimeMillis'])
        end_ms     = int(s['endTimeMillis'])
        dataset_id = f"{start_ms * 1_000_000}-{end_ms * 1_000_000}"
        try:
            res          = fit_service.users().dataSources().datasets().get(
                userId='me', dataSourceId=ds_id, datasetId=dataset_id
            ).execute()
            duracao_sono = sum(
                (int(p['endTimeNanos']) - int(p['startTimeNanos'])) / 3_600_000_000_000
                for p in res.get('point', [])
                if p['value'][0]['intVal'] in FASES_SONO_VALIDAS
            )
            if duracao_sono == 0:
                duracao_sono = (end_ms - start_ms) / 3_600_000
        except Exception:
            duracao_sono = (end_ms - start_ms) / 3_600_000

        duracao_real_por_sessao[s['id']] = duracao_sono

    return duracao_real_por_sessao


def buscar_fases_sono_sessao(fit_service, sessao):
    """
    Para uma sessão específica, devolve minutos e percentagens por fase
    (deep, rem, light, awake) e métricas de BPM.
    """
    ds_id      = "derived:com.google.sleep.segment:com.google.android.gms:merged"
    start_ms   = int(sessao['startTimeMillis'])
    end_ms     = int(sessao['endTimeMillis'])
    dataset_id = f"{start_ms * 1_000_000}-{end_ms * 1_000_000}"
    minutos    = {'deep': 0, 'rem': 0, 'light': 0, 'awake': 0}

    try:
        res = fit_service.users().dataSources().datasets().get(
            userId='me', dataSourceId=ds_id, datasetId=dataset_id
        ).execute()
        for point in res.get('point', []):
            tipo    = point['value'][0]['intVal']
            dur_min = (int(point['endTimeNanos']) - int(point['startTimeNanos'])) / 60_000_000_000
            label   = FASE_LABELS.get(tipo)
            if label:
                minutos[label] += dur_min
    except Exception:
        pass

    total_sono = minutos['deep'] + minutos['rem'] + minutos['light']

    def pct(v):
        return round((v / total_sono * 100) if total_sono > 0 else 0)

    def fmt_min(total):
        return f"{total}m" if total < 70 else f"{total // 60}h {total % 60}m"

    ds_bpm = "derived:com.google.heart_rate.bpm:com.google.android.gms:merge_heart_rate_bpm"
    bpms   = []
    try:
        res_bpm = fit_service.users().dataSources().datasets().get(
            userId='me', dataSourceId=ds_bpm, datasetId=dataset_id
        ).execute()
        bpms = [p['value'][0]['fpVal'] for p in res_bpm.get('point', [])]
    except Exception:
        pass

    return {
        'deep_min':  round(minutos['deep']),
        'deep_fmt':  fmt_min(round(minutos['deep'])),
        'rem_min':   round(minutos['rem']),
        'rem_fmt':   fmt_min(round(minutos['rem'])),
        'light_min': round(minutos['light']),
        'light_fmt': fmt_min(round(minutos['light'])),
        'awake_min': round(minutos['awake']),
        'deep_pct':  pct(minutos['deep']),
        'rem_pct':   pct(minutos['rem']),
        'light_pct': pct(minutos['light']),
        'total_min': round(total_sono),
        'bpm_medio': round(sum(bpms) / len(bpms)) if bpms else 0,
        'bpm_min':   round(min(bpms)) if bpms else 0,
        'bpm_max':   round(max(bpms)) if bpms else 0,
    }


def buscar_bpm_sono(fit_service, sessoes_sono):
    """Para cada sessão de sono, devolve o BPM médio durante esse período."""
    ds_id     = "derived:com.google.heart_rate.bpm:com.google.android.gms:merge_heart_rate_bpm"
    resultado = []

    for s in sessoes_sono:
        start_ms   = int(s['startTimeMillis'])
        end_ms     = int(s['endTimeMillis'])
        dataset_id = f"{start_ms * 1_000_000}-{end_ms * 1_000_000}"
        try:
            res    = fit_service.users().dataSources().datasets().get(
                userId='me', dataSourceId=ds_id, datasetId=dataset_id
            ).execute()
            valores   = [p['value'][0]['fpVal'] for p in res.get('point', [])]
            bpm_medio = round(sum(valores) / len(valores)) if valores else 0
        except Exception:
            bpm_medio = 0

        end_dt = pytz.utc.localize(
            datetime.datetime.utcfromtimestamp(end_ms / 1000)
        ).astimezone(LOCAL_TZ)

        resultado.append({
            'date':  end_dt.date(),
            'label': DIAS_PT.get(end_dt.strftime("%a"), end_dt.strftime("%a")),
            'bpm':   bpm_medio,
        })

    return resultado


def get_weather_data(lat=None, lon=None):
    """Devolve dados meteorológicos via OpenWeatherMap."""
    api_key = "cd86dc586e079435323b617b2d68184e"
    url = (
        f"http://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={api_key}&units=metric"
        if lat and lon else
        f"http://api.openweathermap.org/data/2.5/weather?q=Braga&appid={api_key}&units=metric"
    )
    try:
        r = requests.get(url, timeout=5).json()
        return {
            "temp":           r['main']['temp'],
            "city":           r['name'],
            "sunrise":        r['sys']['sunrise'],
            "sunrise_format": datetime.datetime.fromtimestamp(r['sys']['sunrise']).strftime('%H:%M'),
            "description":    r['weather'][0]['description'],
        }
    except Exception:
        return None


# FUNÇÕES DE PROCESSAMENTO E ANÁLISE

def processar_sono_semanal(sessoes_sono, duracoes_reais, local_tz):
    """
    Processa as sessões e devolve labels e valores para o gráfico semanal.
    Usa a sessão mais longa por dia para evitar duplicados (relógio + telemóvel).
    """
    now_local     = datetime.datetime.now(local_tz)
    dias_semana   = [(now_local - datetime.timedelta(days=i)).date() for i in range(7, 0, -1)]
    labels_semana = [DIAS_PT[d.strftime("%a")] for d in dias_semana]

    sessoes_por_dia = defaultdict(list)
    for s in sessoes_sono:
        duracao_h = duracoes_reais.get(s['id'], 0)
        if duracao_h < 0.25:
            continue
        end_dt = pytz.utc.localize(
            datetime.datetime.utcfromtimestamp(int(s['endTimeMillis']) / 1000)
        ).astimezone(local_tz)
        sessoes_por_dia[end_dt.date()].append(duracao_h)

    dados_sono_grafico = {d: 0.0 for d in dias_semana}
    for dia, duracoes in sessoes_por_dia.items():
        if dia in dados_sono_grafico:
            dados_sono_grafico[dia] = round(max(duracoes), 2)

    return {
        'dias_semana':    dias_semana,
        'labels_semana':  labels_semana,
        'valores_semana': [dados_sono_grafico[d] for d in dias_semana],
        'dados_por_dia':  dados_sono_grafico,
    }


def processar_analise_clinica(sessoes, buckets, todos_bpms, clima):
    """
    Calcula o score semanal de equilíbrio, cards e diagnósticos para o dashboard.
    """
    analise = {
        'score':         0,
        'score_offset':  276,
        'diagnosticos':  [],
        'cards':         {},
        'status_cor':    '#10b981',
        'label_central': "Equilíbrio Semanal",
    }

    if not sessoes:
        return analise

    duracoes = [
        (int(s['endTimeMillis']) - int(s['startTimeMillis'])) / 3_600_000
        for s in sessoes
    ]

    variacao = 0
    if len(duracoes) > 1:
        media_semanal = sum(duracoes) / len(duracoes)
        variacao      = sum(abs(d - media_semanal) for d in duracoes) / len(duracoes)
        score         = max(5, int(100 - (variacao * 15)))
    else:
        score = 100 if duracoes else 0

    analise['score']        = score
    analise['score_offset'] = round(276 - (276 * score / 100), 1)
    analise['status_cor']   = '#10b981' if score >= 85 else '#f59e0b' if score >= 60 else '#ef4444'

    # Cards (última noite)
    ultima         = sessoes[-1]
    duracao_ultima = (int(ultima['endTimeMillis']) - int(ultima['startTimeMillis'])) / 3_600_000
    bpm_medio      = sum(todos_bpms) / len(todos_bpms) if todos_bpms else 0
    passos_dia     = 0
    if buckets:
        pontos = buckets[-1].get('dataset', [{}])[0].get('point', [])
        if pontos:
            passos_dia = pontos[0]['value'][0]['intVal']

    analise['cards'] = {
        'dormido': {'val': f"{duracao_ultima:.1f}h", 'label': 'Última Noite'},
        'bpm':     {'val': f"{int(bpm_medio)}",      'label': 'BPM Médio'},
        'passos':  {'val': passos_dia,                'label': 'Passos Hoje'},
    }

    # Diagnósticos
    if score < 70:
        analise['diagnosticos'].append({
            'nivel': 'warning', 'titulo': "Ritmo Irregular",
            'desc': "A variação entre as tuas horas de sono está elevada. Tenta manter horários mais fixos.",
        })
    if bpm_medio > 75:
        analise['diagnosticos'].append({
            'nivel': 'danger', 'titulo': "Esforço Cardiovascular",
            'desc': "O teu BPM médio está alto. Pode indicar má recuperação ou stress.",
        })
    fim_sono_ts = int(ultima['endTimeMillis']) / 1000
    if clima and fim_sono_ts > (clima['sunrise'] + 7200):
        analise['diagnosticos'].append({
            'nivel': 'warning', 'titulo': "Atraso de Fase",
            'desc': f"Acordou muito após o nascer do sol ({clima['sunrise_format']}).",
        })

    return analise


def calcular_score_regularidade_noite(sessao, todas_sessoes, local_tz):
    """Compara a duração desta noite com a média semanal. Devolve score 0-100."""
    duracoes = [
        (int(s['endTimeMillis']) - int(s['startTimeMillis'])) / 3_600_000
        for s in todas_sessoes
    ]
    if not duracoes:
        return {'score': 0, 'media_h': 0, 'media_m': 0, 'desvio_h': 0, 'desvio_m': 0, 'comparacao': 'neutro'}

    media         = sum(duracoes) / len(duracoes)
    duracao_noite = (int(sessao['endTimeMillis']) - int(sessao['startTimeMillis'])) / 3_600_000
    desvio        = abs(duracao_noite - media)
    score         = max(5, int(100 - (desvio * 20)))
    comparacao    = 'acima' if duracao_noite > media + 0.5 else 'abaixo' if duracao_noite < media - 0.5 else 'normal'

    return {
        'score':      score,
        'media_h':    int(media),
        'media_m':    round((media % 1) * 60),
        'desvio_h':   int(desvio),
        'desvio_m':   round((desvio % 1) * 60),
        'comparacao': comparacao,
    }


def calcular_comparacao_semanal(sessao, todas_sessoes):
    """Compara esta noite com a média semanal e constrói dados para o gráfico."""
    duracoes      = [(int(s['endTimeMillis']) - int(s['startTimeMillis'])) / 3_600_000 for s in todas_sessoes]
    media_duracao = sum(duracoes) / len(duracoes) if duracoes else 0
    duracao_noite = (int(sessao['endTimeMillis']) - int(sessao['startTimeMillis'])) / 3_600_000
    diff_h        = duracao_noite - media_duracao
    noites_piores = sum(1 for d in duracoes if d < duracao_noite)

    grafico = []
    for s in sorted(todas_sessoes, key=lambda x: int(x['startTimeMillis'])):
        end_dt = pytz.utc.localize(
            datetime.datetime.utcfromtimestamp(int(s['endTimeMillis']) / 1000)
        ).astimezone(LOCAL_TZ)
        grafico.append({
            'label':      DIAS_PT[end_dt.strftime('%a')],
            'horas':      round((int(s['endTimeMillis']) - int(s['startTimeMillis'])) / 3_600_000, 2),
            'is_current': s['id'] == sessao['id'],
        })

    return {
        'diff_min':  round(abs(diff_h) * 60),
        'diff_dir':  'mais' if diff_h >= 0 else 'menos',
        'percentil': round(noites_piores / len(duracoes) * 100) if duracoes else 50,
        'media_h':   int(media_duracao),
        'media_m':   round((media_duracao % 1) * 60),
        'grafico':   grafico,
    }


def gerar_insights(fases, passos_dia, clima, sessao, score_reg, local_tz):
    """Gera insights clínicos automáticos para o relatório de uma noite."""
    insights = []

    start_dt = pytz.utc.localize(
        datetime.datetime.utcfromtimestamp(int(sessao['startTimeMillis']) / 1000)
    ).astimezone(local_tz)
    end_dt = pytz.utc.localize(
        datetime.datetime.utcfromtimestamp(int(sessao['endTimeMillis']) / 1000)
    ).astimezone(local_tz)

    if clima:
        sunrise_dt = datetime.datetime.fromtimestamp(clima['sunrise'], tz=local_tz)
        atraso_h   = (end_dt - sunrise_dt).total_seconds() / 3600
        if atraso_h > 2:
            insights.append({
                'tipo': 'warning', 'icon': '🌅', 'titulo': 'Atraso de Fase Solar',
                'desc': (
                    f"Acordaste {round(atraso_h, 1)}h após o nascer do sol ({sunrise_dt.strftime('%H:%M')}). "
                    "A exposição tardia à luz natural atrasa o ritmo circadiano e pode causar "
                    "dificuldade em adormecer nas noites seguintes."
                )
            })

    if start_dt.hour + start_dt.minute / 60 > 2:
        insights.append({
            'tipo': 'warning', 'icon': '🌙', 'titulo': 'Horário Tardio',
            'desc': (
                f"Adormeceste às {start_dt.strftime('%H:%M')}, muito após a meia-noite. "
                "Adormecer consistentemente tarde reduz o sono profundo e aumenta o risco de insónia crónica."
            )
        })

    if score_reg['score'] < 60:
        insights.append({
            'tipo': 'warning', 'icon': '📊', 'titulo': 'Noite Irregular',
            'desc': (
                f"Esta noite desviou {score_reg['desvio_h']}h {score_reg['desvio_m']}m da tua média semanal. "
                "Grandes variações na duração do sono perturbam o ritmo circadiano."
            )
        })

    if fases['deep_pct'] < 10:
        insights.append({
            'tipo': 'danger', 'icon': '🧠', 'titulo': 'Sono Profundo Baixo',
            'desc': f"Apenas {fases['deep_pct']}% de sono profundo (normal: 10-35%). Essencial para recuperação física e consolidação de memórias."
        })
    elif fases['deep_pct'] > 35:
        insights.append({
            'tipo': 'info', 'icon': '💪', 'titulo': 'Sono Profundo Elevado',
            'desc': f"{fases['deep_pct']}% de sono profundo — acima da média. Pode indicar recuperação intensa após esforço físico."
        })

    if fases['rem_pct'] < 10:
        insights.append({
            'tipo': 'warning', 'icon': '💭', 'titulo': 'REM Insuficiente',
            'desc': f"Apenas {fases['rem_pct']}% de sono REM (normal: 10-35%). Crucial para saúde mental, criatividade e processamento emocional."
        })

    if passos_dia > 12000:
        insights.append({
            'tipo': 'info', 'icon': '👟', 'titulo': 'Dia Muito Ativo',
            'desc': (
                f"{passos_dia:,} passos antes desta noite. "
                "Dias intensos tendem a aumentar o sono profundo mas podem fragmentar o sono se o exercício foi feito perto da hora de dormir."
            )
        })
    elif 0 < passos_dia < 3000:
        insights.append({
            'tipo': 'info', 'icon': '🪑', 'titulo': 'Dia Sedentário',
            'desc': f"Apenas {passos_dia:,} passos. A falta de atividade física diurna pode reduzir a qualidade do sono profundo."
        })

    duracao_total = fases['total_min'] + fases['awake_min']
    if duracao_total > 0:
        awake_pct = round(fases['awake_min'] / duracao_total * 100)
        if awake_pct > 10:
            insights.append({
                'tipo': 'warning', 'icon': '😴', 'titulo': 'Fragmentação do Sono',
                'desc': f"Estiveste acordado {fases['awake_min']} min durante a noite ({awake_pct}% do tempo). Sono fragmentado reduz a sensação de descanso e afeta a concentração."
            })

    if fases['bpm_medio'] > 70:
        insights.append({
            'tipo': 'warning', 'icon': '❤️', 'titulo': 'Frequência Cardíaca Elevada',
            'desc': f"BPM médio de {fases['bpm_medio']} durante o sono (ideal: abaixo de 70). Pode indicar stress, má recuperação ou temperatura elevada no quarto."
        })

    return insights


# AUTENTICAÇÃO

def home(request):
    """Página inicial com o botão de login."""
    return render(request, 'sleep_analysis/home.html')


def google_fit_auth(request):
    """Inicia o fluxo OAuth2 com o Google."""
    request.session.pop('oauth_state', None)
    request.session.pop('code_verifier', None)

    client_secrets_path = os.path.join(settings.BASE_DIR, 'client_secret.json')
    flow = Flow.from_client_secrets_file(
        client_secrets_path, scopes=SCOPES,
        redirect_uri='http://127.0.0.1:8000/google-fit/callback/'
    )
    authorization_url, state = flow.authorization_url(access_type='offline', prompt='consent')

    request.session['oauth_state']   = state
    request.session['code_verifier'] = flow.code_verifier
    request.session.modified         = True

    return redirect(authorization_url)


def google_fit_callback(request):
    """Recebe o código de autorização e troca por credenciais."""
    state = request.session.get('oauth_state')
    if not state:
        return redirect('home')

    client_secrets_path = os.path.join(settings.BASE_DIR, 'client_secret.json')
    flow = Flow.from_client_secrets_file(
        client_secrets_path, scopes=SCOPES, state=state,
        redirect_uri='http://127.0.0.1:8000/google-fit/callback/'
    )

    try:
        flow.fetch_token(
            authorization_response=request.build_absolute_uri(),
            code_verifier=request.session.get('code_verifier')
        )
        credentials = flow.credentials
        user_info   = id_token.verify_oauth2_token(
            credentials.id_token, google_requests.Request(), credentials.client_id
        )
        request.session['credentials'] = {
            'token':         credentials.token,
            'refresh_token': credentials.refresh_token,
            'token_uri':     credentials.token_uri,
            'client_id':     credentials.client_id,
            'client_secret': credentials.client_secret,
            'scopes':        credentials.scopes,
        }
        request.session['user_data'] = {
            'name':    user_info.get('name', 'Utilizador'),
            'picture': user_info.get('picture', ''),
        }
        request.session.modified = True
        return redirect('dashboard')
    except Exception as e:
        print(f"Erro no Callback: {e}")
        return redirect('home')


def logout_view(request):
    """Termina sessão e redireciona para a página inicial."""
    request.session.flush()
    return redirect('home')


# PÁGINAS

def doencas(request):
    """Página informativa sobre distúrbios do sono."""
    return render(request, 'sleep_analysis/doencas.html')


def perfil(request):
    """Página de perfil do utilizador."""
    user_data = request.session.get('user_data', {})
    context   = request.session.get('perfil_personalizado', {
        'user_name':       user_data.get('name', 'Ambientes Inteligentes'),
        'sexo':            'Masculino',
        'data_nascimento': '2004-05-08',
        'peso':            60,
        'altura':          180,
        'atividade':       'Sedentário',
        'cronotipo':       'Matutino',
        'meta_horas':      8.0,
    })

    if request.method == "POST":
        context = {k: request.POST.get(k) for k in [
            'user_name', 'sexo', 'data_nascimento', 'peso', 'altura', 'atividade', 'cronotipo', 'meta_horas'
        ]}
        request.session['perfil_personalizado'] = context
        request.session.modified = True
        return redirect('perfil')

    context['modo_edicao'] = request.GET.get('edit') == '1'
    return render(request, 'sleep_analysis/perfil.html', context)


def dashboard(request):
    """Dashboard principal com análise semanal do sono."""
    creds_data = request.session.get('credentials')
    if not creds_data:
        return redirect('google_fit_auth')

    credentials = Credentials(**creds_data)
    fit_service = build('fitness', 'v1', credentials=credentials)
    gf_service  = GoogleFitService(credentials)

    # --- 1. Janela de Tempo ---
    now_local   = datetime.datetime.now(LOCAL_TZ)
    start_local = now_local - datetime.timedelta(days=365)
    start_ms    = int(start_local.timestamp() * 1000)
    end_ms      = int(now_local.timestamp() * 1000)

    # --- 2. Localização e Clima ---
    lat, lon = gf_service.fetch_last_location()
    clima    = get_weather_data(lat, lon)

    # --- 3. Extração de Dados ---
    todos_bpms     = buscar_bpm_detalhado(fit_service, start_ms, end_ms)
    buckets_passos = buscar_passos_agregados(fit_service, start_ms, end_ms)

    sessions_res = fit_service.users().sessions().list(
        userId='me',
        startTime=start_local.astimezone(pytz.utc).strftime('%Y-%m-%dT%H:%M:%S') + 'Z'
    ).execute()

    sessoes_sono = [
        s for s in sessions_res.get('session', [])
        if s['activityType'] == 72
        and (int(s['endTimeMillis']) - int(s['startTimeMillis'])) / 3_600_000 >= 3.0
    ]

    # --- 4. Gráfico Semanal ---
    duracoes_reais = buscar_duracao_real_sono(fit_service, sessoes_sono, LOCAL_TZ)
    sono           = processar_sono_semanal(sessoes_sono, duracoes_reais, LOCAL_TZ)

    # --- 5. Análise Clínica ---
    analise_final = processar_analise_clinica(sessoes_sono, buckets_passos, todos_bpms, clima)

    # --- 6. Sleep Regularity ---
    def hora_para_decimal(dt):
        h = dt.hour + dt.minute / 60
        return round(h - 24 if h > 18 else h, 2)

    regularity_data = []
    for s in sessoes_sono:
        start_dt = pytz.utc.localize(
            datetime.datetime.utcfromtimestamp(int(s['startTimeMillis']) / 1000)
        ).astimezone(LOCAL_TZ)
        end_dt = pytz.utc.localize(
            datetime.datetime.utcfromtimestamp(int(s['endTimeMillis']) / 1000)
        ).astimezone(LOCAL_TZ)
        regularity_data.append({
            'label':     DIAS_PT.get(end_dt.strftime("%a")),
            'sleep':     hora_para_decimal(start_dt),
            'wake':      hora_para_decimal(end_dt),
            'sleep_fmt': start_dt.strftime("%H:%M"),
            'wake_fmt':  end_dt.strftime("%H:%M"),
        })

    # --- 7. Sleep Heart Rate ---
    bpm_sono_data = buscar_bpm_sono(fit_service, sessoes_sono)

    # --- 8. Notificações ---
    verificar_ritmo_e_notificar(regularity_data, request)

    return render(request, 'sleep_analysis/dashboard.html', {
        'analise':         analise_final,
        'clima':           clima,
        'labels_semana':   json.dumps(sono['labels_semana']),
        'valores_semana':  json.dumps(sono['valores_semana']),
        'regularity_data': json.dumps(regularity_data),
        'bpm_sono_data':   json.dumps(bpm_sono_data, default=str),
    })


def relatorio_sono(request):
    """Relatório detalhado de uma noite de sono específica."""
    creds_data = request.session.get('credentials')
    if not creds_data:
        return redirect('google_fit_auth')

    credentials = Credentials(**creds_data)
    fit_service = build('fitness', 'v1', credentials=credentials)

    now_local   = datetime.datetime.now(LOCAL_TZ)
    start_local = now_local - datetime.timedelta(days=365)

    sessions_res = fit_service.users().sessions().list(
        userId='me',
        startTime=start_local.astimezone(pytz.utc).strftime('%Y-%m-%dT%H:%M:%S') + 'Z'
    ).execute()

    sessoes_sono = sorted([
        s for s in sessions_res.get('session', [])
        if s['activityType'] == 72
        and (int(s['endTimeMillis']) - int(s['startTimeMillis'])) / 3_600_000 >= 3.0
    ], key=lambda s: int(s['startTimeMillis']), reverse=True)

    if not sessoes_sono:
        return render(request, 'sleep_analysis/relatorio.html', {'sem_dados': True})

    idx    = max(0, min(int(request.GET.get('noite', 0)), len(sessoes_sono) - 1))
    sessao = sessoes_sono[idx]

    start_ms_s = int(sessao['startTimeMillis'])
    end_ms_s   = int(sessao['endTimeMillis'])
    start_dt   = pytz.utc.localize(datetime.datetime.utcfromtimestamp(start_ms_s / 1000)).astimezone(LOCAL_TZ)
    end_dt     = pytz.utc.localize(datetime.datetime.utcfromtimestamp(end_ms_s / 1000)).astimezone(LOCAL_TZ)
    duracao_h  = (end_ms_s - start_ms_s) / 3_600_000

    fases = buscar_fases_sono_sessao(fit_service, sessao)

    dia_inicio = int(start_dt.replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)
    dia_fim    = int((start_dt - datetime.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)
    buckets    = buscar_passos_agregados(fit_service, dia_fim, dia_inicio)
    passos_dia = 0
    if buckets:
        pontos = buckets[-1].get('dataset', [{}])[0].get('point', [])
        if pontos:
            passos_dia = pontos[0]['value'][0]['intVal']

    gf_service = GoogleFitService(credentials)
    lat, lon   = gf_service.fetch_last_location()
    clima      = get_weather_data(lat, lon)

    score_reg = calcular_score_regularidade_noite(sessao, sessoes_sono, LOCAL_TZ)

    comparacao = calcular_comparacao_semanal(sessao, sessoes_sono)

    insights = gerar_insights(fases, passos_dia, clima, sessao, score_reg, LOCAL_TZ)

    fases_chart   = json.dumps({
        'labels': ['Profundo', 'REM', 'Leve'],
        'values': [fases['deep_min'], fases['rem_min'], fases['light_min']],
        'colors': ['#6366f1', '#10b981', '#3b82f6'],
    })
    semanal_chart = json.dumps({
        'labels':     [d['label']      for d in comparacao['grafico']],
        'values':     [d['horas']      for d in comparacao['grafico']],
        'is_current': [d['is_current'] for d in comparacao['grafico']],
    })

    label_noite = (
        f"{DIAS_SEMANA_PT[end_dt.strftime('%A')]}, "
        f"{end_dt.strftime('%d')} de "
        f"{MESES_PT[end_dt.strftime('%B')]}"
    )

    return render(request, 'sleep_analysis/relatorio.html', {
        'label_noite':   label_noite,
        'start_fmt':     start_dt.strftime('%H:%M'),
        'end_fmt':       end_dt.strftime('%H:%M'),
        'duracao_h':     int(duracao_h),
        'duracao_m':     round((duracao_h % 1) * 60),
        'fases':         fases,
        'fases_chart':   fases_chart,
        'passos_dia':    passos_dia,
        'clima':         clima,
        'score_reg':     score_reg,
        'comparacao':    comparacao,
        'semanal_chart': semanal_chart,
        'insights':      insights,
        'idx':           idx,
        'tem_anterior':  idx < len(sessoes_sono) - 1,
        'tem_seguinte':  idx > 0,
        'total_noites':  len(sessoes_sono),
    })