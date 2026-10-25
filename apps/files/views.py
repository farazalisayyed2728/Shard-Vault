
import os
import json
import hashlib
from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse, StreamingHttpResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods
from django.db import transaction
from django.utils import timezone
from django.conf import settings
from django.core.paginator import Paginator
from .models import StoredFile, StorageNode, Chunk, Replica
from apps.accounts.models import User

def get_local_node():
    node, _ = StorageNode.objects.get_or_create(
        name="Local Node", 
        defaults={'internal_url': 'http://localhost:8000', 'status': 'healthy'}
    )
    return node

@login_required
def dashboard_view(request):
    files = StoredFile.objects.filter(owner=request.user, status='ready', deleted_at__isnull=True).order_by('-created_at')[:5]
    usage_pct = (request.user.used_bytes / request.user.quota_bytes * 100) if request.user.quota_bytes else 0
    context = {
        'recent_files': files,
        'usage_pct': round(usage_pct, 1),
        'used_mb': round(request.user.used_bytes / (1024*1024), 2),
        'quota_mb': round(request.user.quota_bytes / (1024*1024), 2)
    }
    return render(request, 'files/dashboard.html', context)

@login_required
def file_list_view(request):
    query = request.GET.get('q', '')
    files = StoredFile.objects.filter(owner=request.user, deleted_at__isnull=True)
    if query:
        files = files.filter(display_name__icontains=query)
    
    paginator = Paginator(files.order_by('-created_at'), 10)
    page_obj = paginator.get_page(request.GET.get('page'))
    return render(request, 'files/list.html', {'page_obj': page_obj, 'query': query})

@login_required
def trash_view(request):
    files = StoredFile.objects.filter(owner=request.user, deleted_at__isnull=False).order_by('-deleted_at')
    return render(request, 'files/trash.html', {'files': files})

@login_required
@require_http_methods(["POST"])
def init_upload(request):
    data = json.loads(request.body)
    size = int(data.get('size', 0))
    if size > 100 * 1024 * 1024:
        return JsonResponse({'error': 'File exceeds 100MB limit'}, status=400)
    
    if request.user.used_bytes + size > request.user.quota_bytes:
        return JsonResponse({'error': 'Quota exceeded'}, status=400)

    f = StoredFile.objects.create(
        owner=request.user,
        display_name=data.get('name', 'unnamed'),
        original_size=size,
        mime_type=data.get('mime_type', 'application/octet-stream')
    )
    return JsonResponse({'upload_id': str(f.internal_key), 'chunk_size': 4 * 1024 * 1024})

@login_required
@require_http_methods(["PUT"])
def upload_chunk(request, upload_id, index):
    f = get_object_or_404(StoredFile, internal_key=upload_id, owner=request.user, status='uploading')
    data = request.body
    
    chunk_dir = settings.MEDIA_ROOT / 'chunks'
    chunk_dir.mkdir(parents=True, exist_ok=True)
    chunk_path = chunk_dir / f"{f.internal_key}_{index}"
    
    with open(chunk_path, 'wb') as out:
        out.write(data)
        
    checksum = hashlib.sha256(data).hexdigest()
    with transaction.atomic():
        chunk, _ = Chunk.objects.update_or_create(
            file=f, chunk_index=index,
            defaults={'plaintext_size': len(data), 'plaintext_sha256': checksum, 'ciphertext_sha256': checksum}
        )
        Replica.objects.update_or_create(chunk=chunk, storage_node=get_local_node(), defaults={'state': 'ok'})
    return JsonResponse({'status': 'ok'})

@login_required
@require_http_methods(["POST"])
def complete_upload(request, upload_id):
    f = get_object_or_404(StoredFile, internal_key=upload_id, owner=request.user, status='uploading')
    data = json.loads(request.body)
    
    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=request.user.pk)
        if user.used_bytes + f.original_size > user.quota_bytes:
            return JsonResponse({'error': 'Quota exceeded during concurrent upload'}, status=400)
        
        user.used_bytes += f.original_size
        user.save()
        f.status = 'ready'
        f.sha256_checksum = data.get('sha256_checksum', '')
        f.save()
        
    return JsonResponse({'status': 'complete'})

@login_required
def download_file(request, file_id):
    f = get_object_or_404(StoredFile, internal_key=file_id, owner=request.user, status='ready', deleted_at__isnull=True)
    
    def file_iterator():
        for chunk in f.chunk_set.all().order_by('chunk_index'):
            path = settings.MEDIA_ROOT / 'chunks' / f"{f.internal_key}_{chunk.chunk_index}"
            if path.exists():
                with open(path, 'rb') as fp:
                    yield fp.read()

    response = StreamingHttpResponse(file_iterator(), content_type=f.mime_type or 'application/octet-stream')
    response['Content-Disposition'] = f'attachment; filename="{f.display_name}"'
    response['X-Content-Type-Options'] = 'nosniff'
    return response

@login_required
@require_http_methods(["POST"])
def delete_file(request, file_id):
    f = get_object_or_404(StoredFile, internal_key=file_id, owner=request.user, deleted_at__isnull=True)
    f.deleted_at = timezone.now()
    f.save()
    
    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=request.user.pk)
        user.used_bytes = max(0, user.used_bytes - f.original_size)
        user.save()
        
    return redirect('file_list')