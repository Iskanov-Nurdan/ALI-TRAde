from rest_framework import serializers

from apps.accounts.serializers import UserShortSerializer
from apps.core.models import AuditLog


class AuditLogSerializer(serializers.ModelSerializer):
    user = UserShortSerializer(read_only=True)
    action_display = serializers.CharField(source="get_action_display", read_only=True)

    class Meta:
        model = AuditLog
        fields = (
            "id",
            "user",
            "action",
            "action_display",
            "entity_type",
            "entity_id",
            "old_value",
            "new_value",
            "ip_address",
            "created_at",
        )
        read_only_fields = fields
