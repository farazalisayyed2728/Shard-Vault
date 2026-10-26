import concurrent.futures
import hashlib
import json
import secrets

import httpx
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, F, Q
from django.http import Http404, JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django_ratelimit.decorators import ratelimit
from django.views.decorators.http import require_http_methods

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.audit.utils import log_audit
from .constants import REPLICATION_FACTOR
from .models import Chunk, Replica, ShareLink, StorageNode, StoredFile
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

    log_audit(request, 'upload_complete', 'StoredFile', f.internal_key)
    return JsonResponse({'status': 'complete'})

@login_required
@ratelimit(key='user', rate='30/m', block=True)
def download_file(request, file_id):
    f = get_object_or_404(StoredFile, internal_key=file_id, owner=request.user, status='ready', deleted_at__isnull=True)
    log_audit(request, 'download', 'StoredFile', f.internal_key)
    return _stream_file(f)

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
    log_audit(request, 'soft_delete', 'StoredFile', f.internal_key)
    return redirect('file_list')

@login_required
@require_http_methods(["POST"])
def create_share_link(request, file_id):
    f = get_object_or_404(
        StoredFile,
        internal_key=file_id,
        owner=request.user,
        status='ready',
        deleted_at__isnull=True,
    )
    raw_token = secrets.token_urlsafe(32)
    max_downloads_value = request.POST.get('max_downloads')
    try:
        max_downloads = int(max_downloads_value) if max_downloads_value else None
    except ValueError:
        return JsonResponse({'error': 'max_downloads must be a positive integer'}, status=400)
    if max_downloads is not None and max_downloads <= 0:
        return JsonResponse({'error': 'max_downloads must be a positive integer'}, status=400)

    hashed_token = hashlib.sha256(raw_token.encode()).hexdigest()
    ShareLink.objects.create(
        file=f,
        hashed_token=hashed_token,
        created_by=request.user,
        max_downloads=max_downloads,
    )
    log_audit(request, 'share_created', 'ShareLink', f.internal_key)
    return render(request, 'files/share_link.html', {'raw_token': raw_token, 'file': f})

@ratelimit(key='ip', rate='10/m', block=True)
def public_share_download(request, token):
    hashed_token = hashlib.sha256(token.encode()).hexdigest()
    link = get_object_or_404(ShareLink, hashed_token=hashed_token)

    if link.revoked_at or (link.expires_at and link.expires_at < timezone.now()):
        raise Http404("Link expired or revoked.")

    with transaction.atomic():
        link_lock = ShareLink.objects.select_related('file').select_for_update().get(pk=link.pk)
        if link_lock.revoked_at or (link_lock.expires_at and link_lock.expires_at < timezone.now()):
            raise Http404("Link expired or revoked.")
        if link_lock.max_downloads and link_lock.current_downloads >= link_lock.max_downloads:
            raise Http404("Download limit reached.")
        f = link_lock.file
        if f.status != 'ready' or f.deleted_at is not None:
            raise Http404("File not available.")
        link_lock.current_downloads = F('current_downloads') + 1
        link_lock.save(update_fields=['current_downloads'])

    log_audit(request, 'public_download', 'StoredFile', f.internal_key)
    return _stream_file(f)

def _stream_file(f):
    key = bytes(f.wrapped_data_key)

    def file_iterator():
        for chunk in f.chunk_set.all().order_by('chunk_index'):
            replicas = chunk.replica_set.filter(state='ok')
            chunk_data = None
            for rep in replicas:
                path = f"/chunks/{chunk.chunk_uuid}"
                url = f"{rep.storage_node.internal_url}{path}"
                try:
                    r = httpx.get(url, headers=generate_hmac_headers("GET", path), timeout=5.0)
                    if r.status_code == 200:
                        chunk_data = decrypt_data(key, bytes(chunk.encryption_nonce), r.content)
                        break
                except Exception:
                    continue
            if chunk_data is not None:
                yield chunk_data
            else:
                raise Exception("Chunk missing")

    response = StreamingHttpResponse(file_iterator(), content_type=f.mime_type or 'application/octet-stream')
    response['Content-Disposition'] = f'attachment; filename="{f.display_name}"'
    response['X-Content-Type-Options'] = 'nosniff'
    return response

@user_passes_test(lambda u: u.is_staff)
def admin_dashboard(request):
    nodes = StorageNode.objects.all()
    logs = AuditLog.objects.all()[:20]
    return render(request, 'cluster/admin_dashboard.html', {'nodes': nodes, 'logs': logs})


@login_required
@require_http_methods(["GET"])
def cluster_status(request):
    nodes = list(StorageNode.objects.values('name', 'status').order_by('id'))
    under_replicated = (
        Chunk.objects.annotate(
            ok_replicas=Count('replica', filter=Q(replica__state='ok'), distinct=True)
        )
        .filter(ok_replicas__lt=REPLICATION_FACTOR)
        .count()
    )
    return JsonResponse({
        'nodes': nodes,
        'under_replicated': under_replicated,
    })

def custom_404(request, exception):
    return render(request, 'errors/404.html', status=404)

def custom_500(request):
    return render(request, 'errors/500.html', status=500)