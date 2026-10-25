import uuid
from django.db import models
from django.conf import settings

class StorageNode(models.Model):
    name = models.CharField(max_length=100)
    internal_url = models.URLField()
    status = models.CharField(max_length=20, default='healthy')
    last_heartbeat = models.DateTimeField(auto_now_add=True)
    total_storage_bytes = models.BigIntegerField(default=0)
    free_storage_bytes = models.BigIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

class StoredFile(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    display_name = models.CharField(max_length=255)
    internal_key = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    original_size = models.BigIntegerField()
    mime_type = models.CharField(max_length=127, blank=True)
    sha256_checksum = models.CharField(max_length=64, blank=True)
    status = models.CharField(max_length=20, default='uploading')
    deleted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    wrapped_data_key = models.BinaryField(null=True, blank=True)
    key_wrapping_nonce = models.BinaryField(null=True, blank=True)

class Chunk(models.Model):
    file = models.ForeignKey(StoredFile, on_delete=models.CASCADE)
    chunk_index = models.IntegerField()
    plaintext_size = models.IntegerField()
    plaintext_sha256 = models.CharField(max_length=64, blank=True)
    ciphertext_sha256 = models.CharField(max_length=64, blank=True)
    encryption_nonce = models.BinaryField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('file', 'chunk_index')

class Replica(models.Model):
    chunk = models.ForeignKey(Chunk, on_delete=models.CASCADE)
    storage_node = models.ForeignKey(StorageNode, on_delete=models.CASCADE)
    state = models.CharField(max_length=20, default='pending')
    verification_timestamp = models.DateTimeField(auto_now_add=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('chunk', 'storage_node')