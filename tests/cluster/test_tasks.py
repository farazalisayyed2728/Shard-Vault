import hashlib
import json
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch

import httpx
import pytest
from django.test import RequestFactory
from django.utils import timezone

from apps.accounts.models import User
from apps.files.models import Chunk, Replica, StorageNode, StoredFile
from apps.files.tasks import check_node_health, repair_replicas, scrub_replicas
from apps.files.views import cluster_status


@pytest.mark.django_db
def test_repair_replicas_copies_verified_ciphertext():
    user = User.objects.create_user(username='repair-user', password='pw')
    stored_file = StoredFile.objects.create(
        owner=user,
        display_name='test',
        original_size=1,
    )
    ciphertext = b'encrypted chunk'
    chunk = Chunk.objects.create(
        file=stored_file,
        chunk_index=0,
        plaintext_size=1,
        ciphertext_sha256=hashlib.sha256(ciphertext).hexdigest(),
    )
    source = StorageNode.objects.create(
        name='source',
        internal_url='http://source:8000',
        status='healthy',
    )
    targets = [
        StorageNode.objects.create(
            name=f'target-{index}',
            internal_url=f'http://target-{index}:8000',
            status='healthy',
        )
        for index in range(2)
    ]
    Replica.objects.create(chunk=chunk, storage_node=source, state='ok')

    get_response = Mock(status_code=200, content=ciphertext)
    put_response = Mock(status_code=200)
    with patch('apps.files.tasks.httpx.get', return_value=get_response), patch(
        'apps.files.tasks.httpx.put', return_value=put_response
    ):
        repair_replicas()

    assert set(
        chunk.replica_set.filter(state='ok').values_list('storage_node_id', flat=True)
    ) == {source.id, *(node.id for node in targets)}


@pytest.mark.django_db
def test_repair_replicas_does_not_copy_corrupt_source():
    user = User.objects.create_user(username='corrupt-user', password='pw')
    stored_file = StoredFile.objects.create(
        owner=user,
        display_name='test',
        original_size=1,
    )
    chunk = Chunk.objects.create(
        file=stored_file,
        chunk_index=0,
        plaintext_size=1,
        ciphertext_sha256=hashlib.sha256(b'expected').hexdigest(),
    )
    source = StorageNode.objects.create(
        name='source',
        internal_url='http://source:8000',
        status='healthy',
    )
    StorageNode.objects.create(
        name='target',
        internal_url='http://target:8000',
        status='healthy',
    )
    replica = Replica.objects.create(chunk=chunk, storage_node=source, state='ok')

    with patch(
        'apps.files.tasks.httpx.get',
        return_value=Mock(status_code=200, content=b'corrupt'),
    ), patch('apps.files.tasks.httpx.put') as put:
        repair_replicas()

    replica.refresh_from_db()
    assert replica.state == 'corrupt'
    put.assert_not_called()


@pytest.mark.django_db
def test_check_node_health_marks_old_unreachable_node_offline():
    node = StorageNode.objects.create(
        name='offline',
        internal_url='http://offline:8000',
        status='healthy',
    )
    StorageNode.objects.filter(pk=node.pk).update(
        last_heartbeat=timezone.now() - timedelta(seconds=60)
    )

    with patch('apps.files.tasks.httpx.get', side_effect=httpx.ConnectError('down')):
        check_node_health()

    node.refresh_from_db()
    assert node.status == 'offline'


@pytest.mark.django_db
def test_scrub_marks_checksum_mismatch_corrupt():
    user = User.objects.create_user(username='scrub-user', password='pw')
    stored_file = StoredFile.objects.create(
        owner=user,
        display_name='test',
        original_size=1,
    )
    chunk = Chunk.objects.create(
        file=stored_file,
        chunk_index=0,
        plaintext_size=1,
        ciphertext_sha256=hashlib.sha256(b'expected').hexdigest(),
    )
    node = StorageNode.objects.create(
        name='node',
        internal_url='http://node:8000',
        status='healthy',
    )
    replica = Replica.objects.create(chunk=chunk, storage_node=node, state='ok')

    with patch(
        'apps.files.tasks.httpx.get',
        return_value=Mock(status_code=200, content=b'corrupt'),
    ):
        scrub_replicas()

    replica.refresh_from_db()
    assert replica.state == 'corrupt'


@pytest.mark.django_db
def test_cluster_status_reports_nodes_and_under_replicated_chunks():
    user = User.objects.create_user(username='status-user', password='pw')
    stored_file = StoredFile.objects.create(
        owner=user,
        display_name='test',
        original_size=1,
    )
    Chunk.objects.create(file=stored_file, chunk_index=0, plaintext_size=1)
    StorageNode.objects.create(
        name='node-1',
        internal_url='http://node-1:8000',
        status='healthy',
    )
    request = RequestFactory().get('/files/api/status/')
    request.user = SimpleNamespace(is_authenticated=True)

    response = cluster_status(request)

    assert response.status_code == 200
    assert json.loads(response.content) == {
        'nodes': [{'name': 'node-1', 'status': 'healthy'}],
        'under_replicated': 1,
    }
