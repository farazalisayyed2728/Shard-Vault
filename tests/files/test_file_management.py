import hashlib
import json

import pytest

from django.urls import reverse
from apps.accounts.models import User
from apps.files.models import ShareLink, StorageNode, StoredFile
from apps.files.utils import unwrap_data_key

@pytest.fixture
def user(db):
    return User.objects.create_user(username='testu', email='t@t.com', password='pw')

@pytest.mark.django_db
def test_upload_init_quota(client, user):
    client.force_login(user)
    
    # Temporarily lower the user's quota to 10 MB to avoid the 100 MB per-file limit
    user.quota_bytes = 10 * 1024 * 1024
    user.save()
    
    # Try to upload a 15 MB file. It's under 100 MB, but over the 10 MB quota.
    test_size = 15 * 1024 * 1024
    res = client.post(reverse('init_upload'), json.dumps({'name': 'big', 'size': test_size}), content_type='application/json')
    
    assert res.status_code == 400
    assert 'Quota' in res.json()['error']

@pytest.mark.django_db
def test_upload_init_reserves_quota_for_pending_uploads(client, user):
    client.force_login(user)
    user.quota_bytes = 10
    user.save()

    first = client.post(
        reverse('init_upload'),
        json.dumps({'name': 'first', 'size': 7}),
        content_type='application/json',
    )
    second = client.post(
        reverse('init_upload'),
        json.dumps({'name': 'second', 'size': 4}),
        content_type='application/json',
    )

    assert first.status_code == 200
    assert second.status_code == 400
    assert 'Quota' in second.json()['error']

@pytest.mark.django_db
def test_upload_data_key_is_encrypted_at_rest(client, user):
    client.force_login(user)
    response = client.post(
        reverse('init_upload'),
        json.dumps({'name': 'encrypted-key', 'size': 1}),
        content_type='application/json',
    )

    assert response.status_code == 200
    stored_file = StoredFile.objects.get(internal_key=response.json()['upload_id'])
    assert stored_file.key_wrapping_nonce is not None
    assert len(stored_file.wrapped_data_key) > 32
    assert len(unwrap_data_key(stored_file)) == 32

@pytest.mark.django_db
@pytest.mark.parametrize('body', [
    '{"size": -1}',
    '{"size": true}',
    'not-json',
    '[]',
])
def test_upload_init_rejects_invalid_requests(client, user, body):
    client.force_login(user)
    response = client.post(
        reverse('init_upload'),
        body,
        content_type='application/json',
    )
    assert response.status_code == 400

@pytest.mark.django_db
def test_complete_upload_rejects_missing_chunks(client, user):
    client.force_login(user)
    stored_file = StoredFile.objects.create(
        owner=user,
        display_name='incomplete',
        original_size=1,
    )
    response = client.post(
        reverse('complete_upload', args=[stored_file.internal_key]),
        json.dumps({'sha256_checksum': 'a' * 64}),
        content_type='application/json',
    )

    assert response.status_code == 400
    stored_file.refresh_from_db()
    assert stored_file.status == 'uploading'
    user.refresh_from_db()
    assert user.used_bytes == 0

@pytest.mark.django_db
def test_complete_upload_requires_write_quorum(client, user):
    client.force_login(user)
    stored_file = StoredFile.objects.create(
        owner=user,
        display_name='under-replicated',
        original_size=1,
    )
    chunk = stored_file.chunk_set.create(
        chunk_index=0,
        plaintext_size=1,
        plaintext_sha256=hashlib.sha256(b'x').hexdigest(),
    )
    node = StorageNode.objects.create(
        name='one-replica',
        internal_url='http://node:8000',
    )
    chunk.replica_set.create(storage_node=node, state='ok')

    response = client.post(
        reverse('complete_upload', args=[stored_file.internal_key]),
        json.dumps({'sha256_checksum': hashlib.sha256(b'x').hexdigest()}),
        content_type='application/json',
    )

    assert response.status_code == 400
    stored_file.refresh_from_db()
    assert stored_file.status == 'uploading'

@pytest.mark.django_db
def test_complete_upload_accepts_complete_replicated_file(client, user):
    client.force_login(user)
    stored_file = StoredFile.objects.create(
        owner=user,
        display_name='complete',
        original_size=1,
    )
    chunk = stored_file.chunk_set.create(
        chunk_index=0,
        plaintext_size=1,
        plaintext_sha256=hashlib.sha256(b'x').hexdigest(),
    )
    for index in range(2):
        node = StorageNode.objects.create(
            name=f'replica-node-{index}',
            internal_url=f'http://node-{index}:8000',
        )
        chunk.replica_set.create(storage_node=node, state='ok')

    response = client.post(
        reverse('complete_upload', args=[stored_file.internal_key]),
        json.dumps({'sha256_checksum': hashlib.sha256(b'x').hexdigest()}),
        content_type='application/json',
    )

    assert response.status_code == 200
    stored_file.refresh_from_db()
    user.refresh_from_db()
    assert stored_file.status == 'ready'
    assert user.used_bytes == 1

@pytest.mark.django_db
def test_deleting_pending_upload_does_not_reduce_used_quota(client, user):
    client.force_login(user)
    user.used_bytes = 20
    user.save()
    stored_file = StoredFile.objects.create(
        owner=user,
        display_name='pending',
        original_size=10,
    )

    response = client.post(reverse('delete_file', args=[stored_file.internal_key]))

    assert response.status_code == 302
    user.refresh_from_db()
    assert user.used_bytes == 20

@pytest.mark.django_db
def test_deleting_ready_file_releases_quota(client, user):
    client.force_login(user)
    user.used_bytes = 20
    user.save()
    stored_file = StoredFile.objects.create(
        owner=user,
        display_name='ready',
        original_size=7,
        status='ready',
    )

    response = client.post(reverse('delete_file', args=[stored_file.internal_key]))

    assert response.status_code == 302
    user.refresh_from_db()
    assert user.used_bytes == 13

@pytest.mark.django_db
def test_share_link_url_matches_public_download_route(client, user):
    client.force_login(user)
    stored_file = StoredFile.objects.create(
        owner=user,
        display_name='shared',
        original_size=1,
        status='ready',
    )

    response = client.post(reverse('create_share_link', args=[stored_file.internal_key]))

    assert response.status_code == 200
    share_link = ShareLink.objects.get(file=stored_file)
    token = response.context['raw_token']
    assert share_link.hashed_token == hashlib.sha256(token.encode()).hexdigest()
    assert reverse('public_share_download', args=[token]).encode() in response.content

@pytest.mark.django_db
def test_dashboard_renders(client, user):
    client.force_login(user)
    res = client.get(reverse('dashboard'))
    assert res.status_code == 200
    assert b'Storage Usage' in res.content