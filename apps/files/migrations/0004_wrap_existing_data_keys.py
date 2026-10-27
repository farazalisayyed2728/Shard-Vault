import hashlib
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.conf import settings
from django.db import migrations


def _wrapping_key():
    encryption_key = settings.FILE_ENCRYPTION_KEY.encode('utf-8')
    return hashlib.sha256(b"shardvault:file-key-wrap:v1:" + encryption_key).digest()


def wrap_existing_keys(apps, schema_editor):
    StoredFile = apps.get_model('files', 'StoredFile')
    database = schema_editor.connection.alias
    cipher = AESGCM(_wrapping_key())

    for stored_file in StoredFile.objects.using(database).filter(
        wrapped_data_key__isnull=False,
        key_wrapping_nonce__isnull=True,
    ).iterator():
        nonce = os.urandom(12)
        wrapped_key = cipher.encrypt(nonce, bytes(stored_file.wrapped_data_key), None)
        StoredFile.objects.using(database).filter(pk=stored_file.pk).update(
            wrapped_data_key=wrapped_key,
            key_wrapping_nonce=nonce,
        )


def unwrap_existing_keys(apps, schema_editor):
    StoredFile = apps.get_model('files', 'StoredFile')
    database = schema_editor.connection.alias
    cipher = AESGCM(_wrapping_key())

    for stored_file in StoredFile.objects.using(database).filter(
        wrapped_data_key__isnull=False,
        key_wrapping_nonce__isnull=False,
    ).iterator():
        data_key = cipher.decrypt(
            bytes(stored_file.key_wrapping_nonce),
            bytes(stored_file.wrapped_data_key),
            None,
        )
        StoredFile.objects.using(database).filter(pk=stored_file.pk).update(
            wrapped_data_key=data_key,
            key_wrapping_nonce=None,
        )


class Migration(migrations.Migration):

    dependencies = [
        ('files', '0003_sharelink'),
    ]

    operations = [
        migrations.RunPython(wrap_existing_keys, unwrap_existing_keys),
    ]
