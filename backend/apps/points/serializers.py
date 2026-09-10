from rest_framework import serializers

from apps.core.validators import plain_text
from apps.points.models import Point


class PointSerializer(serializers.ModelSerializer):
    class Meta:
        model = Point
        fields = (
            "id",
            "name",
            "address",
            "phone",
            "description",
            "is_active",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class PointShortSerializer(serializers.ModelSerializer):
    class Meta:
        model = Point
        fields = ("id", "name")
        read_only_fields = fields


class PointTextRulesMixin:
    """Общие правила для текстовых полей точки.

    Название, адрес, телефон и описание попадают в списки рейсов, отчёты и
    выгрузки, поэтому очищаются одинаково — и при создании, и при изменении.
    """

    def validate_name(self, value: str) -> str:
        value = plain_text(value).strip()
        if len(value) < 2:
            raise serializers.ValidationError("Название точки слишком короткое.")
        return value

    def validate_address(self, value: str) -> str:
        return plain_text(value).strip()

    def validate_phone(self, value: str) -> str:
        return plain_text(value).strip()

    def validate_description(self, value: str) -> str:
        return plain_text(value)


class PointWriteSerializer(PointTextRulesMixin, serializers.Serializer):
    name = serializers.CharField(max_length=120)
    address = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    phone = serializers.CharField(max_length=30, required=False, allow_blank=True, default="")
    description = serializers.CharField(required=False, allow_blank=True, default="")
    is_active = serializers.BooleanField(default=True)


class PointUpdateSerializer(PointTextRulesMixin, serializers.Serializer):
    name = serializers.CharField(max_length=120, required=False)
    address = serializers.CharField(max_length=255, required=False, allow_blank=True)
    phone = serializers.CharField(max_length=30, required=False, allow_blank=True)
    description = serializers.CharField(required=False, allow_blank=True)
    is_active = serializers.BooleanField(required=False)

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError("Не переданы поля для изменения.")
        return attrs


class SetActiveSerializer(serializers.Serializer):
    is_active = serializers.BooleanField()
