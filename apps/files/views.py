import concurrent.futures
import hashlib
import json

import httpx
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.http import JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from apps.accounts.models import User
from .models import Chunk, Replica, StorageNode, StoredFile
from .utils import (
    decrypt_data,
    encrypt_data,
    generate_encryption_key,
    generate_hmac_headers,
)

@login_required
def dashboard_view(request):
    files = StoredFile.objects.filter(owner=request.user, status='ready', deleted_at__isnull=True).order_by('-created_at')[:5]
    usage_pct = (request.user.used_bytes / request.user.quota_bytes * 100) if request.user.quota_bytes else 0
    return render(request, 'files/dashboard.html', {
        'recent_files': files,
        'usage_pct': round(usage_pct, 1),
        'used_mb': round(request.user.used_bytes / (1024*1024), 2),
        'quota_mb': round(request.user.quota_bytes / (1024*1024), 2)
    })

@login_required
def file_list_view(request):
    query = request.GET.get('q', '')
    files = StoredFile.objects.filter(owner=request.user, deleted_at__isnull=True)
    if query:
        files = files.filter(display_name__icontains=query)
    page_obj = Paginator(files.order_by('-created_at'), 10).get_page(request.GET.get('page'))
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
        mime_type=data.get('mime_type', 'application/octet-stream'),
        wrapped_data_key=generate_encryption_key() 
    )
    return JsonResponse({'upload_id': str(f.internal_key), 'chunk_size': 4 * 1024 * 1024})

@login_required
@require_http_methods(["PUT"])
def upload_chunk(request, upload_id, index):
    f = get_object_or_404(StoredFile, internal_key=upload_id, owner=request.user, status='uploading')
    data = request.body
    key = bytes(f.wrapped_data_key)
    
    # Encrypt
    nonce, ciphertext = encrypt_data(key, data)
    plaintext_hash = hashlib.sha256(data).hexdigest()
    cipher_hash = hashlib.sha256(ciphertext).hexdigest()
    
    # Save Metadata Atomically
    with transaction.atomic():
        chunk, _ = Chunk.objects.update_or_create(
            file=f, chunk_index=index,
            defaults={'plaintext_size': len(data), 'plaintext_sha256': plaintext_hash, 'ciphertext_sha256': cipher_hash, 'encryption_nonce': nonce}
        )
        
    nodes = list(StorageNode.objects.filter(status='healthy'))
    if len(nodes) < 2:
        return JsonResponse({'error': 'Not enough healthy nodes'}, status=503)

    # Distribute to nodes (Write Quorum = 2)
    def send_to_node(node):
        path = f"/chunks/{chunk.chunk_uuid}"
        url = f"{node.internal_url}{path}"
        headers = generate_hmac_headers("PUT", path, ciphertext)
        try:
            r = httpx.put(url, content=ciphertext, headers=headers, timeout=5.0)
            if r.status_code == 200:
                Replica.objects.update_or_create(chunk=chunk, storage_node=node, defaults={'state': 'ok'})
                return True
        except Exception:
            pass
        return False

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        results = list(executor.map(send_to_node, nodes[:3]))
        
    if sum(results) < 2:
        return JsonResponse({'error': 'Write quorum failed'}, status=500)
        
    return JsonResponse({'status': 'ok'})

@login_required
@require_http_methods(["POST"])
def complete_upload(request, upload_id):
    f = get_object_or_404(StoredFile, internal_key=upload_id, owner=request.user, status='uploading')
    
    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=request.user.pk)
        if user.used_bytes + f.original_size > user.quota_bytes:
            return JsonResponse({'error': 'Quota exceeded'}, status=400)
        
        user.used_bytes += f.original_size
        user.save()
        f.status = 'ready'
        f.sha256_checksum = json.loads(request.body).get('sha256_checksum', '')
        f.save()
        
    return JsonResponse({'status': 'complete'})

@login_required
def download_file(request, file_id):
    f = get_object_or_404(StoredFile, internal_key=file_id, owner=request.user, status='ready', deleted_at__isnull=True)
    key = bytes(f.wrapped_data_key)
    
    def file_iterator():
        for chunk in f.chunk_set.all().order_by('chunk_index'):
            replicas = chunk.replica_set.filter(state='ok')
            chunk_data = None
            
            for rep in replicas:
                path = f"/chunks/{chunk.chunk_uuid}"
                url = f"{rep.storage_node.internal_url}{path}"
                headers = generate_hmac_headers("GET", path)
                try:
                    r = httpx.get(url, headers=headers, timeout=5.0)
                    if r.status_code == 200:
                        chunk_data = decrypt_data(key, bytes(chunk.encryption_nonce), r.content)
                        break
                except Exception:
                    continue
                    
            if chunk_data:
                yield chunk_data
            else:
                raise Exception("Chunk missing from all nodes")

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