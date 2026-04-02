from django.urls import path
from . import views

urlpatterns = [
    # O dashboard principal
    path('dashboard/', views.dashboard, name='dashboard'),
    
    # As rotas do Google Fit que usam as funções do teu views.py
    path('google-fit/login/', views.google_fit_auth, name='google_fit_auth'),
    path('google-fit/callback/', views.google_fit_callback, name='google_fit_callback'),
]