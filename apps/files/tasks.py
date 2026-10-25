import hashlib
import logging
from datetime import timedelta

import httpx
from celery import shared_task
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from .constants import REPLICATION_FACTOR
from .models import Chunk, Replica, StorageNode, StoredFile
from .utils import generate_hmac_headers

logger = logging.getLogger(__name__)
NODE_TIMEOUT_SECONDS = 30


def _mark_node_failed(node):
    if (timezone.now() - node.last_heartbeat).total_seconds() > NODE_TIMEOUT_SECONDS:
        node.status = 'offline'
    else:
        node.status = 'degraded'
    node.save(update_fields=['status', 'updated_at'])


def _delete_chunk_from_replicas(chunk):
    path = f'/chunks/{chunk.chunk_uuid}'
    for replica in chunk.replica_set.select_related('storage_node').all():
        try:
            response = httpx.delete(
                f'{replica.storage_node.internal_url}{path}',
                headers=generate_hmac_headers('DELETE', path),
                timeout=5.0,
            )
            if response.status_code not in (200, 404):
                logger.warning(
                    'Could not delete chunk %s from node %s: HTTP %s',
                    chunk.chunk_uuid,
                    replica.storage_node.name,
                    response.status_code,
                )
                return False
        except httpx.HTTPError:
            logger.exception(
                'Could not reach node %s to delete chunk %s',
                replica.storage_node.name,
                chunk.chunk_uuid,
            )
            return False
    return True


@shared_task
def check_node_health():
    """Update node status based on its health endpoint."""
    for node in StorageNode.objects.all():
        try:
            response = httpx.get(f'{node.internal_url}/health', timeout=3.0)
        except httpx.HTTPError:
            logger.warning('Health check failed for node %s', node.name, exc_info=True)
            _mark_node_failed(node)
            continue

        if response.status_code == 200:
            node.status = 'healthy'
            node.last_heartbeat = timezone.now()
            node.save(update_fields=['status', 'last_heartbeat', 'updated_at'])
        else:
            _mark_node_failed(node)


@shared_task
def repair_replicas():
    """Restore chunks to the configured number of healthy storage nodes."""
    under_replicated = (
        Chunk.objects.annotate(
            ok_replicas=Count('replica', filter=Q(replica__state='ok'), distinct=True)
        )
        .filter(ok_replicas__lt=REPLICATION_FACTOR)
        .prefetch_related('replica_set__storage_node')
        .distinct()
    )

    for chunk in under_replicated:
        replicas = list(chunk.replica_set.all())
        healthy_replicas = [replica for replica in replicas if replica.state == 'ok']
        healthy_replica_node_ids = {replica.storage_node_id for replica in healthy_replicas}
        candidates = list(
            StorageNode.objects.filter(status='healthy')
            .exclude(id__in=healthy_replica_node_ids)
            .order_by('id')
        )
        if not candidates:
            logger.warning('No healthy target nodes available for chunk %s', chunk.chunk_uuid)
            continue

        path = f'/chunks/{chunk.chunk_uuid}'
        ciphertext = None
        for source_replica in healthy_replicas:
            try:
                response = httpx.get(
                    f'{source_replica.storage_node.internal_url}{path}',
                    headers=generate_hmac_headers('GET', path),
                    timeout=10.0,
                )
                if response.status_code != 200:
                    logger.warning(
                        'Could not read chunk %s from node %s: HTTP %s',
                        chunk.chunk_uuid,
                        source_replica.storage_node.name,
                        response.status_code,
                    )
                    continue
                candidate_ciphertext = response.content
                if hashlib.sha256(candidate_ciphertext).hexdigest() != chunk.ciphertext_sha256:
                    source_replica.state = 'corrupt'
                    source_replica.save(update_fields=['state', 'updated_at'])
                    logger.error(
                        'Checksum mismatch for chunk %s on node %s',
                        chunk.chunk_uuid,
                        source_replica.storage_node.name,
                    )
                    continue
                ciphertext = candidate_ciphertext
                break
            except httpx.HTTPError:
                logger.exception(
                    'Could not reach source node %s for chunk %s',
                    source_replica.storage_node.name,
                    chunk.chunk_uuid,
                )

        if ciphertext is None:
            logger.error('No verified source replica available for chunk %s', chunk.chunk_uuid)
            continue

        for target_node in candidates:
            if len(healthy_replica_node_ids) >= REPLICATION_FACTOR:
                break
            try:
                response = httpx.put(
                    f'{target_node.internal_url}{path}',
                    content=ciphertext,
                    headers=generate_hmac_headers('PUT', path, ciphertext),
                    timeout=10.0,
                )
                if response.status_code != 200:
                    logger.warning(
                        'Could not repair chunk %s to node %s: HTTP %s',
                        chunk.chunk_uuid,
                        target_node.name,
                        response.status_code,
                    )
                    continue
                with transaction.atomic():
                    Replica.objects.update_or_create(
                        chunk=chunk,
                        storage_node=target_node,
                        defaults={'state': 'ok', 'verification_timestamp': timezone.now()},
                    )
                healthy_replica_node_ids.add(target_node.id)
                logger.info('Repaired chunk %s to node %s', chunk.chunk_uuid, target_node.name)
            except httpx.HTTPError:
                logger.exception(
                    'Could not reach target node %s for chunk %s',
                    target_node.name,
                    chunk.chunk_uuid,
                )


@shared_task
def scrub_replicas():
    """Verify ciphertext hashes for the 100 least recently checked replicas."""
    replicas = (
        Replica.objects.filter(state='ok')
        .select_related('chunk', 'storage_node')
        .order_by('verification_timestamp')[:100]
    )
    for replica in replicas:
        path = f'/chunks/{replica.chunk.chunk_uuid}'
        try:
            response = httpx.get(
                f'{replica.storage_node.internal_url}{path}',
                headers=generate_hmac_headers('GET', path),
                timeout=5.0,
            )
        except httpx.HTTPError:
            logger.warning(
                'Could not scrub chunk %s on node %s',
                replica.chunk.chunk_uuid,
                replica.storage_node.name,
                exc_info=True,
            )
            continue

        if response.status_code == 404:
            replica.state = 'missing'
            replica.save(update_fields=['state', 'updated_at'])
        elif response.status_code != 200:
            logger.warning(
                'Scrub request for chunk %s on node %s returned HTTP %s',
                replica.chunk.chunk_uuid,
                replica.storage_node.name,
                response.status_code,
            )
        elif hashlib.sha256(response.content).hexdigest() != replica.chunk.ciphertext_sha256:
            replica.state = 'corrupt'
            replica.save(update_fields=['state', 'updated_at'])
            logger.error(
                'Checksum mismatch for chunk %s on node %s',
                replica.chunk.chunk_uuid,
                replica.storage_node.name,
            )
        else:
            replica.verification_timestamp = timezone.now()
            replica.save(update_fields=['verification_timestamp', 'updated_at'])


@shared_task
def cleanup_stale_uploads():
    """Remove abandoned upload metadata after deleting its stored chunks."""
    threshold = timezone.now() - timedelta(hours=24)
    stale_files = StoredFile.objects.filter(status='uploading', created_at__lt=threshold)
    for stored_file in stale_files.prefetch_related('chunk_set__replica_set__storage_node'):
        chunks = list(stored_file.chunk_set.all())
        if all(_delete_chunk_from_replicas(chunk) for chunk in chunks):
            stored_file.delete()


@shared_task
def garbage_collect_trash():
    """Remove trashed files and their remote chunks after the retention period."""
    threshold = timezone.now() - timedelta(days=7)
    trashed_files = StoredFile.objects.filter(deleted_at__lt=threshold)
    for stored_file in trashed_files.prefetch_related('chunk_set__replica_set__storage_node'):
        chunks = list(stored_file.chunk_set.all())
        if all(_delete_chunk_from_replicas(chunk) for chunk in chunks):
            stored_file.delete()
