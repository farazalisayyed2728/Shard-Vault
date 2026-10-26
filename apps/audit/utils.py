from .models import AuditLog

def log_audit(request, action, obj_type, obj_id, meta=None):
    ip = request.META.get('REMOTE_ADDR')
    user_agent = request.META.get('HTTP_USER_AGENT', '')
    actor = request.user if request.user.is_authenticated else None
    AuditLog.objects.create(
        actor=actor, action=action, object_type=obj_type,
        object_id=str(obj_id), ip_address=ip, user_agent=user_agent,
        metadata=meta or {}
    )