import pytest
from django.urls import reverse

@pytest.mark.django_db
def test_user_registration(client):
    url = reverse('register')
    response = client.post(url, {
        'username': 'testuser',
        'email': 'test@example.com',
        'password': 'StrongPassword123'
    })
    assert response.status_code in [200, 302]

@pytest.mark.django_db
def test_health_endpoint(client):
    response = client.get(reverse('health'))
    assert response.status_code == 200
    assert response.json()['status'] == 'ok'