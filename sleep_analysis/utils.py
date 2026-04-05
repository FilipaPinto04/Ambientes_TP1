import xml.etree.ElementTree as ET
import pandas as pd
from .models import DiarioSaude 

def parse_apple_health_para_django(file_path):
    context = ET.iterparse(file_path, events=("end",))
    records_list = []
    
    mapa_sono = {'0': 'InBed', '1': 'AsleepUnspecified', '2': 'Awake', '3': 'Core', '4': 'Deep', '5': 'REM'}
    tipos_interessantes = [
        'HKQuantityTypeIdentifierStepCount', 'HKQuantityTypeIdentifierHeartRate',
        'HKQuantityTypeIdentifierAppleExerciseTime', 'HKCategoryTypeIdentifierSleepAnalysis'
    ]

    for event, elem in context:
        if elem.tag == 'Record':
            tipo = elem.get('type')
            if tipo in tipos_interessantes:
                try:
                    tipo_limpo = tipo.replace('HKQuantityTypeIdentifier', '').replace('HKCategoryTypeIdentifier', '')
                    valor_raw = elem.get('value')
                    
                    if tipo_limpo == 'SleepAnalysis':
                        valor_final = mapa_sono.get(valor_raw, valor_raw)
                    else:
                        valor_final = float(valor_raw) if valor_raw else 0

                    records_list.append({
                        'tipo': tipo_limpo,
                        'valor': valor_final,
                        'data_inicio': pd.to_datetime(elem.get('startDate')),
                        'data_fim': pd.to_datetime(elem.get('endDate'))
                    })
                except: continue
            elem.clear()
    
    if not records_list: return

    df = pd.DataFrame(records_list)
    df['dia'] = df['data_inicio'].dt.date
    df['duracao_min'] = (df['data_fim'] - df['data_inicio']).dt.total_seconds() / 60

    for dia, grupo in df.groupby('dia'):
        passos = grupo[grupo['tipo'] == 'StepCount']['valor'].sum()
        exe_min = grupo[grupo['tipo'] == 'AppleExerciseTime']['valor'].sum()
        hr_med = grupo[grupo['tipo'] == 'HeartRate']['valor'].mean()
        sono_p = grupo[grupo['tipo'] == 'Deep']['duracao_min'].sum()
        
        alerta_msg = ""
        if passos > 10000 and sono_p < 60:
            alerta_msg = "Atividade elevada com pouco sono profundo. Risco de fadiga."

        DiarioSaude.objects.update_or_create(
            data=dia,
            defaults={
                'passos': passos,
                'exercicio_min': exe_min,
                'hr_media': round(hr_med, 1) if not pd.isna(hr_med) else 0,
                'sono_profundo_min': sono_p,
                'alerta': alerta_msg
            }
        )