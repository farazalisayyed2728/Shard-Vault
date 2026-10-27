import pytest
from django.urls import reverse
from apps.accounts.models import User
from apps.files.models import StoredFile

@pytest.fixture
def users(db):
    u1 = User.objects.create_user(username='u1', email='1@t.com', password='pw')
    u2 = User.objects.create_user(username='u2', email='2@t.com', password='pw')
    admin = User.objects.create_superuser(username='admin', email='a@t.com', password='pw')
    return u1, u2, admin

@pytest.mark.django_db
def test_ownership_isolation(client, users):
    u1, u2, admin = users
    # U1 creates file
    f = StoredFile.objects.create(owner=u1, display_name="f", original_size=1, status='ready')
    
    # U2 tries to delete it
    client.force_login(u2)
    res = client.post(reverse('delete_file', args=[f.internal_key]))
    assert res.status_code == 404 # Isolated safely
    
@pytest.mark.django_db
def test_admin_dashboard_access(client, users):
    u1, u2, admin = users
    
    # Regular user denied
    client.force_login(u1)
    assert client.get(reverse('admin_dashboard')).status_code == 302
    
    # Admin allowed
    client.force_login(admin)
    assert client.get(reverse('admin_dashboard')).status_code == 200