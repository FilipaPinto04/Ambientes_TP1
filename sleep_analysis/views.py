from django.shortcuts import render, redirect
from .utils import parse_apple_health_para_django
from .models import DiarioSaude
import json
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt


# Esta é a função que o Django não estava a encontrar
def dashboard(request):
    dados = DiarioSaude.objects.all().order_by('data')
    
    context = {
        'labels': json.dumps([str(d.data) for d in dados]),
        'passos': json.dumps([d.passos for d in dados]),
        'sono_profundo': json.dumps([d.sono_profundo_min for d in dados]),
        'registos': dados,
    }
    return render(request, 'sleep_analysis/dashboard.html', context)

@csrf_exempt # Essencial para que o iPhone consiga enviar dados sem login
def api_receber_saude(request):
    if request.method == 'POST':
        try:
            dados = json.loads(request.body)
            # O 'dados' aqui será o JSON vindo do iPhone
            
            # Exemplo de processamento simplificado do JSON:
            DiarioSaude.objects.update_or_create(
                data=dados['data'],
                defaults={
                    'passos': dados.get('passos', 0),
                    'sono_profundo_min': dados.get('sono_profundo', 0),
                    'hr_media': dados.get('batimentos', 0),
                    'alerta': "Sincronizado via iPhone"
                }
            )
            return JsonResponse({"status": "OK", "msg": "Dados atualizados!"})
        except Exception as e:
            return JsonResponse({"status": "Erro", "msg": str(e)}, status=400)
    
    return JsonResponse({"status": "Metodo nao permitido"}, status=405)