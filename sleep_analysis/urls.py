from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('api/saude/', views.api_receber_saude, name='api_saude'), # Adiciona aqui!
]