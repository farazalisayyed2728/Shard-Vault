import pytest
import json
from django.urls import reverse
from apps.accounts.models import User
from apps.files.models import StoredFile

@pytest.fixture
def user(db):
    return User.objects.create_user(username='testu', email='t@t.com', password='pw')

@pytest.mark.django_db
def test_upload_init_quota(client, user):
    client.force_login(user)
    # Test quota bypass
    huge_size = int(user.quota_bytes) + 1024
    res = client.post(reverse('init_upload'), json.dumps({'name': 'big', 'size': huge_size}), content_type='application/json')
    assert res.status_code == 400
    assert 'Quota' in res.json()['error']

@pytest.mark.django_db
def test_dashboard_renders(client, user):
    client.force_login(user)
    res = client.get(reverse('dashboard'))
    assert res.status_code == 200
    assert b'Storage Usage' in res.content