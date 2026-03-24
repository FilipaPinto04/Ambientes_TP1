from django.db import models

class DiarioSaude(models.Model):  # <--- Verifica se o nome está IGUAL aqui
    data = models.DateField(unique=True)
    passos = models.IntegerField(default=0)
    exercicio_min = models.FloatField(default=0.0)
    hr_media = models.FloatField(default=0.0)
    sono_profundo_min = models.FloatField(default=0.0)
    alerta = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"Dados de {self.data}"