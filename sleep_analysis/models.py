from django.db import models

class MetricaSaude(models.Model):
    # Mantemos os teus campos originais para compatibilidade
    timestamp = models.DateTimeField(auto_now_add=True)
    tipo = models.CharField(max_length=50)  # 'sleep', 'steps', 'heart_rate'
    valor = models.FloatField()

    # --- ADICIONAMOS ESTES PARA A "VIBE NOITE" E CIÊNCIA ---
    
    # Localização e Sol (Vindo do OpenWeatherMap)
    cidade = models.CharField(max_length=100, default="Braga")
    hora_sunset = models.TimeField(null=True, blank=True)
    hora_sunrise = models.TimeField(null=True, blank=True)

    # Classificação Clínica (Para o Dashboard)
    # Ex: "Sono de Elite", "Défice de Recuperação"
    titulo_classificacao = models.CharField(max_length=100, blank=True)
    cor_exibicao = models.CharField(max_length=20, default="#81d4fa") # Azul Noite
    emoji_estado = models.CharField(max_length=10, default="🌙")
    
    # O "Porquê" científico
    alerta_detalhado = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.tipo} | {self.titulo_classificacao} ({self.timestamp.date()})"