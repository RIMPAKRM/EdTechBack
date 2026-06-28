from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.http import Http404
from django.contrib.auth import get_user_model
import secrets

from api.models import StudentProfile, TeacherProfile, TeacherInviteCode, Group, Lesson, Subject
from api.permissions import IsAdmin
from api.serializers import LessonCreateSerializer, LessonSerializer

User = get_user_model()


class AdminDashboardView(APIView):
    permission_classes = [IsAdmin]

    def get(self, request):
        return Response(
            {
                "users": User.objects.count(),
                "students": StudentProfile.objects.count(),
                "teachers": TeacherProfile.objects.count(),
                "invite_codes": TeacherInviteCode.objects.count(),
            }
        )


class AdminInviteCodeView(APIView):
    permission_classes = [IsAdmin]

    def post(self, request):
        code = secrets.token_hex(4).upper()
        obj = TeacherInviteCode.objects.create(code=code, is_active=True)

        return Response({"code": obj.code, "expires_in_minutes": obj.ttl_minutes})


class AdminGroupLessonsView(APIView):
    permission_classes = [IsAdmin]

    def _get_group(self, group_id):
        try:
            return Group.objects.get(pk=group_id)
        except Group.DoesNotExist:
            raise Http404("Группа не найдена")

    def _lesson_qs(self, group):
        return Lesson.objects.filter(group=group).select_related("teacher", "subject", "group")

    def get(self, request, group_id):
        group = self._get_group(group_id)
        lessons = self._lesson_qs(group)
        serializer = LessonSerializer(lessons, many=True)
        return Response({"group": group.name, "lessons": serializer.data})

    def post(self, request, group_id):
        group = self._get_group(group_id)

        payload = request.data
        if isinstance(payload, dict) and payload.get("lessons") is not None:
            payload = payload.get("lessons")
        if isinstance(payload, dict):
            payload = [payload]
        if not isinstance(payload, list) or not payload:
            return Response({"detail": "Ожидается объект урока или список lessons"}, status=status.HTTP_400_BAD_REQUEST)

        created = []
        errors = []

        for idx, item in enumerate(payload):
            serializer = LessonCreateSerializer(data=item)
            if not serializer.is_valid():
                errors.append({"index": idx, "errors": serializer.errors})
                continue

            validated = serializer.validated_data
            if type(validated) is not dict:
                return Response({"detail": "Ожидается объект урока"}, status=status.HTTP_400_BAD_REQUEST)

            validated["group"] = group
            validated["teacher"] = validated.get("teacher") or (group.teachers.first() if group.teachers.exists() else None)

            lesson = Lesson(**validated)

            try:
                lesson.full_clean()
                lesson.save()
                created.append(LessonSerializer(lesson).data)
            except Exception as exc:
                errors.append({"index": idx, "errors": str(exc)})

        return Response({"created": created, "errors": errors}, status=status.HTTP_201_CREATED)


class AdminGroupLessonDetailView(APIView):
    permission_classes = [IsAdmin]

    def _get_group_and_lesson(self, group_id, lesson_id):
        try:
            group = Group.objects.get(pk=group_id)
        except Group.DoesNotExist:
            raise Http404("Группа не найдена")

        try:
            lesson = Lesson.objects.select_related("teacher", "subject").get(pk=lesson_id, group=group)
        except Lesson.DoesNotExist:
            raise Http404("Урок не найден в этой группе")

        return group, lesson

    def get(self, request, group_id, lesson_id):
        _, lesson = self._get_group_and_lesson(group_id, lesson_id)
        serializer = LessonSerializer(lesson)
        return Response(serializer.data)

    def patch(self, request, group_id, lesson_id):
        _, lesson = self._get_group_and_lesson(group_id, lesson_id)

        partial = True
        serializer = LessonSerializer(lesson, data=request.data, partial=partial)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        serializer.save()
        return Response(serializer.data)

    def delete(self, request, group_id, lesson_id):
        _, lesson = self._get_group_and_lesson(group_id, lesson_id)
        lesson.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
