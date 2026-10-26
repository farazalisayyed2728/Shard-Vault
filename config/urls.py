from django.contrib import admin
from django.urls import path, include
from django.views.generic import RedirectView

from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/', include('apps.accounts.urls')),
    path('files/', include('apps.files.urls')),
    path('', RedirectView.as_view(url='/files/dashboard/', permanent=False), name='home'),

    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
]

handler404 = 'apps.files.views.custom_404'
handler500 = 'apps.files.views.custom_500'