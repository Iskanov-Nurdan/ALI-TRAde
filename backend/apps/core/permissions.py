from rest_framework.permissions import SAFE_METHODS, BasePermission


class IsAdmin(BasePermission):
    """Доступ только для главного администратора."""

    message = "Требуются права администратора."

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.is_admin)


class IsAdminOrReadOnly(BasePermission):
    """Чтение — всем авторизованным, запись — только администратору."""

    message = "Изменение доступно только администратору."

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated):
            return False
        if request.method in SAFE_METHODS:
            return True
        return user.is_admin
