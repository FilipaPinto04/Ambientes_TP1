import xml.etree.ElementTree as ET
import pandas as pd

def parse_apple_health_completo(file_path):
    print("A processar dados.")
    
    context = ET.iterparse(file_path, events=("start",))
    records_list = []
    
    # Lista de tipos que queremos extrair (podes adicionar mais aqui)
    tipos_interessantes = [
        'HKQuantityTypeIdentifierStepCount',          # Passos
        'HKQuantityTypeIdentifierHeartRate',          # Batimentos
    ]

    for event, elem in context:
        if elem.tag == 'Record':
            tipo = elem.get('type')
            if tipo in tipos_interessantes:
                try:
                    data = {
                        'tipo': tipo.replace('HKQuantityTypeIdentifier', ''),
                        'valor': float(elem.get('value')) if elem.get('value') else 0,
                        'unidade': elem.get('unit'),
                        'data': elem.get('startDate')
                    }
                    records_list.append(data)
                except:
                    continue
            elem.clear()

    if not records_list:
        print("Não foram encontrados dados biomédicos.")
        return None

    df = pd.DataFrame(records_list)
    df['data'] = pd.to_datetime(df['data'])
    return df

# Execução
df_final = parse_apple_health_completo('export.xml')

if df_final is not None:
    df_final.to_csv('dados_biomédicos.csv', index=False)
    print("\nFicheiro 'dados_biomédicos.csv' criado com sucesso!")