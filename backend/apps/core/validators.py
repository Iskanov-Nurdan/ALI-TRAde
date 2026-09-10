"""Проверки пользовательского текста, общие для всех приложений."""
import re

from rest_framework import serializers

HTML_TAG = re.compile(r"<\s*/?\s*[a-zA-Z][^>]*>")
# Управляющие символы, кроме перевода строки и табуляции
CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def plain_text(value: str) -> str:
    """Возвращает очищенный текст либо поднимает ошибку валидации.

    Разметка в комментариях и описаниях не нужна, а её хранение делает уязвимым
    любого стороннего потребителя API, который выведет значение как HTML.
    """
    if not isinstance(value, str):
        return value
    # Управляющие символы убираются ДО проверки на разметку. В обратном порядке
    # строка "<\x01script>" не совпадает с HTML_TAG (после "<" ожидается буква),
    # а очистка затем собирает из неё рабочий тег.
    cleaned = CONTROL_CHARS.sub("", value)
    if HTML_TAG.search(cleaned):
        raise serializers.ValidationError("HTML-разметка в тексте не допускается.")
    return cleaned
