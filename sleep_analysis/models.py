from django.db import models

class RegistroSaude(models.Model):
    TIPOS = [
        ('SLEEP', 'Sono'),
        ('HEART', 'Batimento Cardíaco'),
        ('STEPS', 'Passos'),
        ('ACTIVITY', 'Atividade Física'),
    ]
    
    data = models.DateField()
    tipo = models.CharField(max_length=10, choices=TIPOS)
    valor_principal = models.FloatField()  # Ex: Horas totais, Passos totais
    detalhes = models.JSONField(default=dict)  # Aqui guardamos fases do sono ou variabilidade de BPM
    score_dia = models.IntegerField(default=0) # Calculado cientificamente
    
    class Meta:
        unique_together = ('data', 'tipo')