from rest_framework.permissions import BasePermission
from api.models import TeacherProfile, StudentProfile
from django.contrib.auth.models import User


class IsTeacher(BasePermission):
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        return TeacherProfile.objects.filter(user=request.user).exists()


class IsStudent(BasePermission):
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        return StudentProfile.objects.filter(user=request.user).exists()


class IsAdmin(BasePermission):
    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and getattr(request.user, "is_staff", False)
        )
