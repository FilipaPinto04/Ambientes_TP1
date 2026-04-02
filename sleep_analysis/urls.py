from django.urls import path
from . import views

urlpatterns = [
    # Página de Boas-Vindas (Landing Page)
    path('', views.home, name='home'),
    
    # Dashboard Principal (Gráfico e Análise)
    path('dashboard/', views.google_fit_auth, name='dashboard'),    
    
    # Página de Informações sobre Doenças do Sono
    path('doencas/', views.doencas, name='doencas'),
    
    # Página de Perfil do Utilizador
    path('perfil/', views.perfil, name='perfil'),

    path('logout/', views.logout_view, name='logout'),
    
    # Rotas de Autenticação com Google Fit
    path('google-fit/login/', views.google_fit_auth, name='google_fit_auth'),
    path('google-fit/callback/', views.google_fit_callback, name='google_fit_callback'),
]