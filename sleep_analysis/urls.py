from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    
    # O Dashboard volta a ser uma página de visualização, não de autenticação
    path('dashboard/', views.dashboard, name='dashboard'),    
    
    path('doencas/', views.doencas, name='doencas'),
    path('perfil/', views.perfil, name='perfil'),
    path('logout/', views.logout_view, name='logout'),
    
    # Rotas de Autenticação puras
    path('google-fit/login/', views.google_fit_auth, name='google_fit_auth'),
    path('google-fit/callback/', views.google_fit_callback, name='google_fit_callback'),
]