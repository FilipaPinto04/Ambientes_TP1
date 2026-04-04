from googleapiclient.discovery import build
import datetime

class GoogleFitService:
    def __init__(self, credentials):
        self.service = build('fitness', 'v1', credentials=credentials)

    def _get_nanoseconds(self, days=7):
        now = datetime.datetime.utcnow()
        start = (now - datetime.timedelta(days=days)).replace(hour=0, minute=0, second=0)
        return {
            'start': int(start.timestamp() * 1e9),
            'end': int(now.timestamp() * 1e9),
            'start_ms': int(start.timestamp() * 1000),
            'end_ms': int(now.timestamp() * 1000)
        }

    def fetch_daily_metrics(self):
        time_info = self._get_nanoseconds()
        
        body = {
            "aggregateBy": [
                {"dataTypeName": "com.google.step_count.delta"},
                {"dataTypeName": "com.google.heart_rate.summary"} # O culpado está aqui
            ],
            "bucketByTime": {"durationMillis": 86400000},
            "startTimeMillis": time_info['start_ms'],
            "endTimeMillis": time_info['end_ms']
        }

        try:
            # Tenta buscar os dados
            response = self.service.users().dataset().aggregate(userId='me', body=body).execute()
        except Exception as e:
            # Se der erro (como o 400 da imagem), criamos uma resposta vazia manual
            print(f"Aviso: Não foram encontrados dados de sensores: {e}")
            return []
        
        metrics_by_day = []
        for bucket in response.get('bucket', []):
            date = datetime.datetime.fromtimestamp(int(bucket['startTimeMillis']) / 1000).date()
            
            day_data = {
                'date': date,
                'steps': 0,
                'bpm_avg': 0,
                'bpm_max': 0,
                'bpm_min': 0
            }

            for dataset in bucket.get('dataset', []):
                for point in dataset.get('point', []):
                    # Extração de Passos
                    if 'step_count.delta' in dataset['dataSourceId']:
                        day_data['steps'] = point['value'][0]['intVal']
                    
                    # Extração de Heart Rate (Média, Max, Min)
                    if 'heart_rate.summary' in dataset['dataSourceId']:
                        day_data['bpm_avg'] = round(point['value'][0]['fpVal'], 1)
                        day_data['bpm_max'] = point['value'][1]['fpVal']
                        day_data['bpm_min'] = point['value'][2]['fpVal']
            
            metrics_by_day.append(day_data)
            
        return metrics_by_day