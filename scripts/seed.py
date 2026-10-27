import os
import sys
from pathlib import Path

import django

sys.path.append(str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
django.setup()

from apps.files.models import StorageNode  # noqa: E402


nodes = [
    ("Node 1", "http://node1:8000"),
    ("Node 2", "http://node2:8000"),
    ("Node 3", "http://node3:8000"),
]

for name, url in nodes:
    node, created = StorageNode.objects.get_or_create(
        name=name,
        defaults={"internal_url": url, "status": "healthy"},
    )
    if created:
        print(f"Created {name} at {url}")
    else:
        print(f"{name} already exists.")

print("Seed complete: 3 storage nodes registered.")
