import xml.etree.ElementTree as ET
import pandas as pd

file_path = 'export.xml'


def parse_apple_health_completo(file_path):
    print("A processar dados do Apple Health... Isto pode demorar dependendo do tamanho do ficheiro.")
    
    #osvnodnvs<wjviogewnkvs
    # # Usamos iterparse para não carregar o XML todo na memória (eficiente para ficheiros grandes)
    context = ET.iterparse(file_path, events=("start", "end"))
    
    records_list = []
    
    # Dicionário para mapear os valores do sono da Apple
    mapa_sono = {
        '0': 'InBed',
        '1': 'AsleepUnspecified',
        '2': 'Awake',
        '3': 'Core',   # Sono Leve/Essencial
        '4': 'Deep',   # Sono Profundo
        '5': 'REM'     # Sono REM
    }

    # Lista de tipos que queremos extrair
    tipos_interessantes = [
        'HKQuantityTypeIdentifierStepCount',                # Passos
        'HKQuantityTypeIdentifierHeartRate',                # Batimentos
        'HKQuantityTypeIdentifierAppleExerciseTime',        # Tempo de Exercício (Minutos)
        'HKQuantityTypeIdentifierActiveEnergyBurned',       # Calorias Ativas
        'HKQuantityTypeIdentifierHeartRateVariabilitySDNN', # HRV (Stress/Recuperação)
        'HKCategoryTypeIdentifierSleepAnalysis'             # Fases do Sono
    ]

    for event, elem in context:
        if event == "end":
            # --- PROCESSAR RECORDS (Métricas de Saúde e Sono) ---
            if elem.tag == 'Record':
                tipo = elem.get('type')
                if tipo in tipos_interessantes:
                    try:
                        valor_raw = elem.get('value')
                        tipo_limpo = tipo.replace('HKQuantityTypeIdentifier', '').replace('HKCategoryTypeIdentifier', '')
                        
                        # Lógica especial para traduzir os códigos de sono
                        if tipo_limpo == 'SleepAnalysis':
                            valor_final = mapa_sono.get(valor_raw, valor_raw)
                        else:
                            valor_final = float(valor_raw) if valor_raw else 0

                        data = {
                            'fonte': 'Record',
                            'tipo': tipo_limpo,
                            'valor': valor_final,
                            'unidade': elem.get('unit', 'N/A'),
                            'data_inicio': elem.get('startDate'),
                            'data_fim': elem.get('endDate')
                        }
                        records_list.append(data)
                    except Exception as e:
                        continue
                
                # Importante: limpar o elemento para libertar memória RAM
                elem.clear()

            # --- PROCESSAR WORKOUTS (Treinos registados manualmente) ---
            elif elem.tag == 'Workout':
                try:
                    data = {
                        'fonte': 'Workout',
                        'tipo': elem.get('workoutActivityType').replace('HKWorkoutActivityType', ''),
                        'valor': float(elem.get('duration')), # Duração do treino
                        'unidade': elem.get('durationUnit'),
                        'data_inicio': elem.get('startDate'),
                        'data_fim': elem.get('endDate')
                    }
                    records_list.append(data)
                except:
                    continue
                elem.clear()

    if not records_list:
        print("Não foram encontrados dados biomédicos relevantes.")
        return None

    # Criar DataFrame
    df = pd.DataFrame(records_list)
    
    # Converter datas para formato datetime do Pandas
    df['data_inicio'] = pd.to_datetime(df['data_inicio'])
    df['data_fim'] = pd.to_datetime(df['data_fim'])
    
    return df

# --- Execução ---
# Substitui 'export.xml' pelo nome real do teu ficheiro
df_final = parse_apple_health_completo('export.xml')

if df_final is not None:
    # Guardar o CSV
    df_final.to_csv('dados_saude_completos.csv', index=False)
    print(f"\nSucesso! Foram extraídos {len(df_final)} registos.")
    print("Ficheiro 'dados_saude_completos.csv' criado.")
    
    # Mostrar um pequeno resumo para verificares se o REM e Exercício aparecem
    print("\nResumo de tipos encontrados:")
    print(df_final['tipo'].value_counts())