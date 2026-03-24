@ -0,0 +1,82 @@
import pandas as pd

def realizar_analise_inteligente(csv_path):
    # 1. Carregar os dados
    df = pd.read_csv(csv_path)
    
    # Converter colunas de data para formato datetime
    df['data_inicio'] = pd.to_datetime(df['data_inicio'])
    df['data_fim'] = pd.to_datetime(df['data_fim'])
    
    # Criar a coluna 'dia' para agrupar (extrair apenas a data)
    df['dia'] = df['data_inicio'].dt.date
    
    # Calcular a duração em minutos para cada registo (útil para o sono)
    df['duracao_minutos'] = (df['data_fim'] - df['data_inicio']).dt.total_seconds() / 60

    print(f"Analisando dados de {df['dia'].nunique()} dias...\n")

    # 2. Agrupar métricas por dia
    # Para passos e exercício -> Soma (Sum)
    # Para batimentos e HRV -> Média (Mean)
    # Para sono -> Soma da duração por fase
    
    resumo_diario = []

    for dia, grupo in df.groupby('dia'):
        # Métricas de Atividade
        passos = grupo[grupo['tipo'] == 'StepCount']['valor'].sum()
        exercicio_min = grupo[grupo['tipo'] == 'AppleExerciseTime']['valor'].sum()
        
        # Métricas de Coração (Média em repouso/sono costuma ser mais baixa)
        hr_media = grupo[grupo['tipo'] == 'HeartRate']['valor'].mean()
        hrv_media = grupo[grupo['tipo'] == 'HeartRateVariabilitySDNN']['valor'].mean()
        
        # Métricas de Sono (Filtrar por fases)
        sono_deep = grupo[grupo['tipo'] == 'Deep']['duracao_minutos'].sum()
        sono_rem = grupo[grupo['tipo'] == 'REM']['duracao_minutos'].sum()
        sono_total = grupo[grupo['tipo'].isin(['Core', 'Deep', 'REM'])]['duracao_minutos'].sum()

        resumo_diario.append({
            'dia': dia,
            'passos': passos,
            'exercicio_min': exercicio_min,
            'hr_media': round(hr_media, 1),
            'hrv_recuperacao': round(hrv_media, 1),
            'min_sono_total': round(sono_total, 1),
            'min_sono_profundo': round(sono_deep, 1),
            'min_sono_rem': round(sono_rem, 1)
        })

    df_resumo = pd.DataFrame(resumo_diario)

    # 3. Lógica de Decisão (O "Cérebro" do Ambiente Inteligente)
    alertas = []
    for _, row in df_resumo.iterrows():
        msg = ""
        # Regra 1: Cansaço vs Sono Profundo
        if row['passos'] > 10000 and row['min_sono_profundo'] < 60:
            msg = f"Dia {row['dia']}: Atividade alta ({int(row['passos'])} passos), mas pouco sono profundo. Recomenda-se relaxamento antes de dormir."
        
        # Regra 2: Possível Insónia (muito tempo na cama, pouco sono efetivo - se tivesses InBed)
        elif row['min_sono_total'] > 0 and row['min_sono_total'] < 360: # Menos de 6h
            msg = f"Dia {row['dia']}: Sono insuficiente ({int(row['min_sono_total'])} min). Risco de fadiga acrescido."
            
        # Regra 3: Recuperação Cardíaca
        elif row['hr_media'] > 85 and row['min_sono_total'] > 0:
            msg = f"Dia {row['dia']}: Frequência cardíaca média elevada durante o repouso. Verifique stress ou cafeína."

        if msg:
            alertas.append(msg)
            
    return df_resumo, alertas

# --- EXECUÇÃO ---
resumo, lista_alertas = realizar_analise_inteligente('dados_saude_completos.csv')

# Guardar o resumo diário para o teu dashboard
resumo.to_csv('resumo_diario_analisado.csv', index=False)

print("--- ALERTAS GERADOS ---")
for a in lista_alertas:
    print(f"-> {a}") 