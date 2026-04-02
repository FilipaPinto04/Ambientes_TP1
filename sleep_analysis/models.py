from django.db import models

class MetricaSaude(models.Model):
    timestamp = models.DateTimeField()
    tipo = models.CharField(max_length=50) # 'steps', 'heart_rate', etc
    valor = models.FloatField()

    def __str__(self):
        return f"{self.tipo} em {self.timestamp}"