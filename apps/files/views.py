import concurrent.futures
import hashlib
import json
import math
import re
import secrets

import httpx
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, F, Q, Sum
from django.http import Http404, JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import content_disposition_header
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
    unwrap_data_key,
    wrap_data_key,
)

MAX_FILE_SIZE = 100 * 1024 * 1024
CHUNK_SIZE = 4 * 1024 * 1024


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
@ratelimit(key='user', rate='10/m', block=True)
def init_upload(request):
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({'error': 'Invalid JSON request body'}, status=400)
    if not isinstance(data, dict):
        return JsonResponse({'error': 'Request body must be a JSON object'}, status=400)

    size = data.get('size')
    if not isinstance(size, int) or isinstance(size, bool) or size < 0:
        return JsonResponse({'error': 'size must be a non-negative integer'}, status=400)
    if size > MAX_FILE_SIZE:
        return JsonResponse({'error': 'File exceeds 100MB limit'}, status=400)

    name = data.get('name', 'unnamed')
    mime_type = data.get('mime_type', 'application/octet-stream')
    if not isinstance(name, str) or not name.strip() or len(name) > 255:
        return JsonResponse({'error': 'name must be a non-empty string of at most 255 characters'}, status=400)
    if not isinstance(mime_type, str) or len(mime_type) > 127:
        return JsonResponse({'error': 'mime_type must be a string of at most 127 characters'}, status=400)

    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=request.user.pk)
        pending_bytes = (
            StoredFile.objects.filter(
                owner=user,
                status='uploading',
                deleted_at__isnull=True,
            ).aggregate(total=Sum('original_size'))['total']
            or 0
        )
        if user.used_bytes + pending_bytes + size > user.quota_bytes:
            return JsonResponse({'error': 'Quota exceeded'}, status=400)

        wrapped_data_key, key_wrapping_nonce = wrap_data_key(generate_encryption_key())
        stored_file = StoredFile.objects.create(
            owner=user,
            display_name=name.strip(),
            original_size=size,
            mime_type=mime_type or 'application/octet-stream',
            wrapped_data_key=wrapped_data_key,
            key_wrapping_nonce=key_wrapping_nonce,
        )
    return JsonResponse({'upload_id': str(stored_file.internal_key), 'chunk_size': CHUNK_SIZE})

@login_required
@require_http_methods(["PUT"])
@ratelimit(key='user', rate='100/m', block=True)
def upload_chunk(request, upload_id, index):
    f = get_object_or_404(
        StoredFile,
        internal_key=upload_id,
        owner=request.user,
        status='uploading',
        deleted_at__isnull=True,
    )
    expected_chunks = math.ceil(f.original_size / CHUNK_SIZE)
    if index < 0 or index >= expected_chunks:
        return JsonResponse({'error': 'Chunk index is outside the upload'}, status=400)

    data = request.body
    expected_size = min(CHUNK_SIZE, f.original_size - index * CHUNK_SIZE)
    if len(data) != expected_size:
        return JsonResponse({'error': 'Chunk size does not match the expected size'}, status=400)

    key = unwrap_data_key(f)
    nonce, ciphertext = encrypt_data(key, data)
    plaintext_hash = hashlib.sha256(data).hexdigest()
    cipher_hash = hashlib.sha256(ciphertext).hexdigest()

    with transaction.atomic():
        f = get_object_or_404(
            StoredFile.objects.select_for_update(),
            pk=f.pk,
            owner=request.user,
            status='uploading',
            deleted_at__isnull=True,
        )
        chunk, _ = Chunk.objects.update_or_create(
            file=f, chunk_index=index,
            defaults={
                'plaintext_size': len(data),
                'plaintext_sha256': plaintext_hash,
                'ciphertext_sha256': cipher_hash,
                'encryption_nonce': nonce,
            },
        )
        chunk.replica_set.update(state='pending')

    nodes = list(StorageNode.objects.filter(status='healthy'))
    if len(nodes) < 2:
        return JsonResponse({'error': 'Not enough healthy nodes'}, status=503)

    def send_to_node(node):
        path = f"/chunks/{chunk.chunk_uuid}"
        url = f"{node.internal_url}{path}"
        headers = generate_hmac_headers("PUT", path, ciphertext)
        try:
            r = httpx.put(url, content=ciphertext, headers=headers, timeout=5.0)
            if r.status_code == 200:
                Replica.objects.update_or_create(chunk=chunk, storage_node=node, defaults={'state': 'ok'})
                return True
        except httpx.HTTPError:
            return False
        return False

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        results = list(executor.map(send_to_node, nodes[:3]))

    if sum(results) < 2:
        return JsonResponse({'error': 'Write quorum failed'}, status=500)

    return JsonResponse({'status': 'ok'})

@login_required
@require_http_methods(["POST"])
def complete_upload(request, upload_id):
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({'error': 'Invalid JSON request body'}, status=400)
    if not isinstance(data, dict):
        return JsonResponse({'error': 'Request body must be a JSON object'}, status=400)
    checksum = data.get('sha256_checksum', '')
    if not isinstance(checksum, str) or not re.fullmatch(r'[0-9a-f]{64}', checksum):
        return JsonResponse({'error': 'A valid SHA-256 checksum is required'}, status=400)

    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=request.user.pk)
        f = get_object_or_404(
            StoredFile.objects.select_for_update(),
            internal_key=upload_id,
            owner=user,
            status='uploading',
            deleted_at__isnull=True,
        )
        if user.used_bytes + f.original_size > user.quota_bytes:
            return JsonResponse({'error': 'Quota exceeded'}, status=400)

        chunks = f.chunk_set.order_by('chunk_index')
        expected_count = math.ceil(f.original_size / CHUNK_SIZE)
        if chunks.count() != expected_count:
            return JsonResponse({'error': 'Upload is missing chunks'}, status=400)
        for expected_index, chunk in enumerate(chunks):
            expected_size = min(CHUNK_SIZE, f.original_size - expected_index * CHUNK_SIZE)
            if chunk.chunk_index != expected_index or chunk.plaintext_size != expected_size:
                return JsonResponse({'error': 'Uploaded chunks are incomplete or invalid'}, status=400)
            if chunk.replica_set.filter(state='ok').count() < 2:
                return JsonResponse({'error': 'A chunk does not have the required write quorum'}, status=400)

        user.used_bytes += f.original_size
        user.save()
        f.status = 'ready'
        f.sha256_checksum = checksum
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
    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=request.user.pk)
        f = get_object_or_404(
            StoredFile.objects.select_for_update(),
            internal_key=file_id,
            owner=user,
            deleted_at__isnull=True,
        )
        if f.status == 'ready':
            user.used_bytes = max(0, user.used_bytes - f.original_size)
            user.save(update_fields=['used_bytes'])
        f.deleted_at = timezone.now()
        f.save(update_fields=['deleted_at', 'updated_at'])
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
@require_http_methods(["GET"])
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
    key = unwrap_data_key(f)

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
    response['Content-Disposition'] = content_disposition_header(
        as_attachment=True,
        filename=f.display_name,
    )
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