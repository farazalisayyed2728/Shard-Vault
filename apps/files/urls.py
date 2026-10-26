from django.urls import path
from . import views

urlpatterns = [
    path('dashboard/', views.dashboard_view, name='dashboard'),
    path('my-files/', views.file_list_view, name='file_list'),
    path('trash/', views.trash_view, name='trash'),
    path('api/uploads/', views.init_upload, name='init_upload'),
    path('api/uploads/<uuid:upload_id>/chunks/<int:index>/', views.upload_chunk, name='upload_chunk'),
    path('api/uploads/<uuid:upload_id>/complete/', views.complete_upload, name='complete_upload'),
    path('api/status/', views.cluster_status, name='cluster_status'),
    path('download/<uuid:file_id>/', views.download_file, name='download_file'),
    path('delete/<uuid:file_id>/', views.delete_file, name='delete_file'),
    path('share/<uuid:file_id>/', views.create_share_link, name='create_share_link'),
    path('shared/<str:token>/', views.public_share_download, name='public_share_download'),
    path('admin-dashboard/', views.admin_dashboard, name='admin_dashboard'),
]