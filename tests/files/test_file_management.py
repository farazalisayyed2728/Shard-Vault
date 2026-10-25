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
    
    # Temporarily lower the user's quota to 10 MB to avoid the 100 MB per-file limit
    user.quota_bytes = 10 * 1024 * 1024
    user.save()
    
    # Try to upload a 15 MB file. It's under 100 MB, but over the 10 MB quota.
    test_size = 15 * 1024 * 1024
    res = client.post(reverse('init_upload'), json.dumps({'name': 'big', 'size': test_size}), content_type='application/json')
    
    assert res.status_code == 400
    assert 'Quota' in res.json()['error']

@pytest.mark.django_db
def test_dashboard_renders(client, user):
    client.force_login(user)
    res = client.get(reverse('dashboard'))
    assert res.status_code == 200
    assert b'Storage Usage' in res.content