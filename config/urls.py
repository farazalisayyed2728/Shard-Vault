from django.contrib import admin
from django.urls import path, include
from django.views.generic import RedirectView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/', include('apps.accounts.urls')),
    path('files/', include('apps.files.urls')),
    path('', RedirectView.as_view(url='/files/dashboard/', permanent=False), name='home'),
]