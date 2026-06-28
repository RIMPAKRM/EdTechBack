from rest_framework import generics, viewsets, status
from rest_framework.decorators import action, api_view
from rest_framework.exceptions import PermissionDenied
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.views import APIView
from django.utils import timezone
from django.db import transaction, IntegrityError
from django.shortcuts import get_object_or_404
from django.http import JsonResponse
from api.notification_utils import create_notification
import random

from typing import Any
import secrets

from api.models import (
    Assignment,
    Group,
    GroupInviteCode,
    StudentProfile,
    TeacherProfile,
    TeacherInviteCode,
    ShopItem,
    Purchase,
    Subject,
    Lesson,
    Attendance,
    StudentStatistics,
    MonthlyAverageGrade,
    DailyQuest,
    StudentDailyQuest,
    Badge,
    StudentBadge,
    LevelReward,
    RouletteBet,
)
from api.serializers import (
    RegisterSerializer,
    LoginSerializer,
    ShopItemSerializer,
    PurchaseSerializer,
    StudentProfileSerializer,
    TeacherProfileSerializer,
    GroupSerializer,
    AssignmentSerializer,
    LessonSerializer,
    LessonCreateSerializer,
    AttendanceSerializer,
    StudentStatisticsSerializer,
)

from api.permissions import ( 
    IsTeacher, IsStudent, IsAdmin 
)
from api.utils import update_daily_quests, check_and_award_badges, generate_daily_quests

__all__ = [
    "RegisterView",
    "LoginView",
    "GroupViewSet",
    "AssignmentViewSet",
    "StudentAssignmentFeedView",
    "TeacherAssignmentFeedView",
    "GroupInviteCodeView",
    "StudentJoinGroupView",
    "LessonViewSet",
    "ScheduleView",
    "TeacherStudentsView",
    "StudentAssignmentsView",
    "GradeAssignmentView",
    "CurrentLessonView",
    "StudentStatisticsView",
    "GroupLeaderboardView",
    "MonthlyGradesView",
]

class ShopItemListView(generics.ListAPIView):
    serializer_class = ShopItemSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        queryset = ShopItem.objects.filter(is_active=True)
        if hasattr(self.request.user, 'studentprofile'):
            student = self.request.user.studentprofile
            queryset = queryset.filter(required_level__lte=student.level)
        return queryset


class BuyItemView(APIView):
    """Покупка товара учеником"""
    permission_classes = [IsAuthenticated, IsStudent]

    def post(self, request, item_id):
        try:
            item = ShopItem.objects.get(id=item_id, is_active=True)
        except ShopItem.DoesNotExist:
            return Response({"error": "Товар не найден или недоступен"}, status=status.HTTP_404_NOT_FOUND)

        with transaction.atomic():
            student = StudentProfile.objects.select_for_update().get(user=request.user)

            if student.crystals < item.price:
                return Response({"error": "Недостаточно кристаллов"}, status=status.HTTP_400_BAD_REQUEST)

            student.crystals -= item.price
            student.save(update_fields=['crystals'])

            purchase = Purchase.objects.create(student=student, item=item)
            xp_amount = item.price // 2
            if xp_amount > 0:
                student.add_xp(xp_amount, f"Покупка: {item.name}")
        update_daily_quests(student, 'buy_item')
        check_and_award_badges(student)

        return Response({
            "message": "Успешная покупка",
            "purchase": PurchaseSerializer(purchase, context={'request': request}).data,
            "balance": student.crystals
        }, status=status.HTTP_201_CREATED)


class MyPurchasesView(generics.ListAPIView):
    """Список покупок ученика"""
    serializer_class = PurchaseSerializer
    permission_classes = [IsAuthenticated, IsStudent]

    def get_queryset(self):
        student = self.request.user.studentprofile
        purchases = Purchase.objects.filter(student=student)
        
        for p in purchases.filter(status='pending', expires_at__lt=timezone.now()):
            p.check_expiration()
            
        return purchases


class ActivatePurchaseView(APIView):
    """Активация покупки учеником"""
    permission_classes = [IsAuthenticated, IsStudent]

    def post(self, request, purchase_id):
        student = request.user.studentprofile
        try:
            purchase = Purchase.objects.get(id=purchase_id, student=student)
        except Purchase.DoesNotExist:
            return Response({"error": "Покупка не найдена"}, status=status.HTTP_404_NOT_FOUND)

        purchase.check_expiration()

        if purchase.status != 'pending':
            return Response({"error": f"Невозможно активировать. Текущий статус: {purchase.get_status_display()}"}, 
                            status=status.HTTP_400_BAD_REQUEST)

        purchase.status = 'activated'
        purchase.activated_at = timezone.now()
        purchase.save(update_fields=['status', 'activated_at'])

        return Response({"message": "Товар успешно активирован!"}, status=status.HTTP_200_OK)


class TeacherStudentPurchasesView(generics.ListAPIView):
    """Просмотр покупок конкретного ученика учителем"""
    serializer_class = PurchaseSerializer
    permission_classes = [IsAuthenticated, IsTeacher]

    def get_queryset(self):
        student_id = self.kwargs.get('student_id')
        return Purchase.objects.filter(student_id=student_id)




class ChangeCrystalsView(APIView):
    permission_classes = [IsAuthenticated, IsTeacher]

    def post(self, request, student_id):
        teacher = TeacherProfile.objects.filter(user=request.user).first()
        if not teacher:
            raise PermissionDenied("Только преподы могут выдавать кристалики")
        student = StudentProfile.objects.get(id=student_id)
        if student.group and not student.group.teachers.filter(pk=teacher.pk).exists():
            raise PermissionDenied("Этот студент не в вашей группе")
        amount = int(request.data.get("amount", 0))
        student.crystals += amount
        if student.crystals < 0:
            student.crystals = 0
        student.save()
        create_notification(
            recipient=student.user,
            notification_type='crystals_awarded',
            title='Начислены кристаллы',
            message=f'Вам начислено {amount} кристаллов. Текущий баланс: {student.crystals}',
            sender=request.user,
            link='/shop'
            )
        return Response({
            "student_id": student.pk,
            "crystals": student.crystals
        })



class RegisterView(generics.CreateAPIView):
    serializer_class = RegisterSerializer
    permission_classes = [AllowAny]


class LoginView(generics.GenericAPIView):
    serializer_class = LoginSerializer

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(serializer.validated_data)


class MyStudentProfileView(generics.RetrieveUpdateAPIView):
    serializer_class = StudentProfileSerializer
    permission_classes = [IsAuthenticated, IsStudent]
    parser_classes = [MultiPartParser, FormParser]

    def get_object(self) -> Any:
        return StudentProfile.objects.get(user=self.request.user)


class MyStudentAvatarView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def patch(self, request):
        if hasattr(request.user, "studentprofile"):
            profile = request.user.studentprofile
        elif hasattr(request.user, "teacherprofile"):
            profile = request.user.teacherprofile
        else:
            return Response({"detail": "Нет профиля"}, status=400)

        avatar = request.FILES.get("avatar")
        if not avatar:
            return Response({"detail": "Файл не передан"}, status=400)

        profile.avatar = avatar
        profile.save()
        return Response({
            "avatar_url": request.build_absolute_uri(profile.avatar.url)
        })


class MyStudentAvatarDeleteView(APIView):
    permission_classes = [IsAuthenticated, IsStudent]
    parser_classes = [MultiPartParser, FormParser]

    def get(self, request):
        student = StudentProfile.objects.get(user=request.user)
        if student.avatar:
            return Response({
                "avatar_url": request.build_absolute_uri(student.avatar.url)
            })
        return Response({"avatar_url": None}, status=204)

    def post(self, request):
        student = StudentProfile.objects.get(user=request.user)
        avatar = request.FILES.get("avatar")
        if not avatar:
            return Response({"detail": "Требуется файл аватара"}, status=400)
        if student.avatar:
            student.avatar.delete(save=False)
        student.avatar = avatar
        student.save()
        return Response({
            "avatar_url": request.build_absolute_uri(student.avatar.url)
        })

    def delete(self, request):
        student = StudentProfile.objects.get(user=request.user)
        try:
            if student.avatar:
                student.avatar.delete(save=False)
                student.avatar = None
                student.save()

            return Response({"detail": "Аватар успешно удалён"})
        except Exception as e:
            return Response({"detail": "Ошибка при удалении аватара", "error": str(e)}, status=500)


class MyTeacherProfileView(generics.RetrieveUpdateAPIView):
    serializer_class = TeacherProfileSerializer
    permission_classes = [IsAuthenticated, IsTeacher]

    def get_object(self) -> Any:
        return TeacherProfile.objects.get(user=self.request.user)


class PublicStudentProfileView(generics.RetrieveAPIView):
    serializer_class = StudentProfileSerializer
    queryset = StudentProfile.objects.all()
    permission_classes = [IsAuthenticated]


class PublicTeacherProfileView(generics.RetrieveAPIView):
    serializer_class = TeacherProfileSerializer
    queryset = TeacherProfile.objects.all()
    permission_classes = [IsAuthenticated]


class StudentViewSet(viewsets.ModelViewSet):
    queryset = StudentProfile.objects.all()
    serializer_class = StudentProfileSerializer
    permission_classes = [IsAuthenticated, IsTeacher]


class TeacherViewSet(viewsets.ModelViewSet):
    queryset = TeacherProfile.objects.all()
    serializer_class = TeacherProfileSerializer
    permission_classes = [IsAuthenticated, IsTeacher]


class GroupViewSet(viewsets.ModelViewSet):
    queryset = Group.objects.all()
    serializer_class = GroupSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        teacher = TeacherProfile.objects.filter(user=user).first()
        if teacher:
            return Group.objects.filter(teacher=teacher)

        student = StudentProfile.objects.filter(user=user).first()
        if student and student.group:
            return Group.objects.filter(pk=student.group.pk)

        return Group.objects.none()

    def perform_create(self, serializer):
        teacher = TeacherProfile.objects.filter(user=self.request.user).first()
        if not teacher:
            raise PermissionDenied("Создавать группы могут только преподаватели")
        serializer.save(teachers=[teacher])

    def perform_update(self, serializer):
        group = self.get_object()
        if not group.teachers.filter(user=self.request.user).exists():
            raise PermissionDenied("Только препод который владеет группой может её редачить")
        serializer.save()

    def perform_destroy(self, instance):
        if not instance.teachers.filter(user=self.request.user).exists():
            raise PermissionDenied("Только препод который владеет группой может её удалить")
        instance.delete()


class AssignmentViewSet(viewsets.ModelViewSet):
    queryset = Assignment.objects.all()
    serializer_class = AssignmentSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        teacher = TeacherProfile.objects.filter(user=user).first()
        if teacher:
            return Assignment.objects.filter(teacher=teacher)

        student = StudentProfile.objects.filter(user=user).first()
        if student and student.group:
            return Assignment.objects.filter(group=student.group).exclude(
                status=Assignment.Status.REVOKED
            )
            

        assignment = serializer.instance
        students = StudentProfile.objects.filter(group=assignment.group)
        for student in students:
            create_notification(
            recipient=student.user,
            notification_type='new_assignment',
            title='Новое задание',
            message=f'Появилось новое задание: "{assignment.title}". Срок до {assignment.due_date.strftime("%d.%m.%Y %H:%M")}',
            sender=request.user,
            link=f'/assignments/{assignment.id}'
        )
        return Assignment.objects.none()

    def perform_create(self, serializer):
        teacher = TeacherProfile.objects.filter(user=self.request.user).first()
        if not teacher:
            raise PermissionDenied("Только преподы могут выдавать задания")

        group = serializer.validated_data.get("group")
        if not group.teachers.filter(pk=teacher.pk).exists():
            raise PermissionDenied(
                "Это не ваша группа!"
            )

        serializer.save(teacher=teacher)

    def update(self, request, *args, **kwargs):
        assignment = self.get_object()
        teacher = TeacherProfile.objects.filter(user=request.user).first()
        student = StudentProfile.objects.filter(user=request.user).first()
        new_status = request.data.get("status")

        if student:
            if assignment.group != student.group:
                raise PermissionDenied(
                    "Вы не состоите в этой группе"
                )

            invalid_fields = set(request.data.keys()) - {"status", "answer"}
            if invalid_fields:
                raise PermissionDenied(
                    f"Недопустимые поля: {', '.join(invalid_fields)}. "
                    "Нужны только: status, answer."
                )
            if assignment.status == Assignment.Status.ISSUED:
                student.add_xp(15, f"Сдача задания: {assignment.title}")
                update_daily_quests(student, 'submit_assignment')
                check_and_award_badges(student)
            create_notification(
                    recipient=assignment.teacher.user,
                    notification_type='assignment_submitted',
                    title=f'Сдано задание "{assignment.title}"',
                    message=f'Ученик {student.user.first_name} {student.user.last_name} отправил решение.',
                    sender=request.user,
                    link=f'/teacher/assignments/{assignment.id}'
                )

            new_status = request.data.get("status")
            answer_text = request.data.get("answer")

            if new_status != Assignment.Status.SUBMITTED:
                raise PermissionDenied("Можно отправлять только сделанное задание (status = submitted)")

            if not answer_text or not isinstance(answer_text, str) or len(answer_text.strip()) == 0:
                raise PermissionDenied("Ответ не может быть пустым (минимум 1 символ)")

            if len(answer_text) > 4096:
                raise PermissionDenied("Ответ не может быть длиннее 4096 символов")

            if assignment.status != Assignment.Status.ISSUED:
                raise PermissionDenied("Отправить решение можно только в ответ на выданное задание")

            if "group" in request.data and request.data["group"] != assignment.group.id:
                raise PermissionDenied("Вы не можете изменить группу этого задания")

            try:
                student = StudentProfile.objects.get(user=request.user)
            except StudentProfile.DoesNotExist:
                pass
            else:
                if assignment.status == Assignment.Status.ISSUED:
                    student.add_xp(15, f"Сдача задания: {assignment.title}")
                    update_daily_quests(student, 'submit_assignment')
                    check_and_award_badges(student)


        elif teacher:

            if assignment.teacher != teacher:
                raise PermissionDenied(
                    "Вы можете управлять только своими заданиями"
                )

            if "group" in request.data and request.data["group"] != assignment.group.id:
                raise PermissionDenied(
                    "Нельзя изменить группу задания после создания"
                )

            if (
                assignment.status == Assignment.Status.GRADED
                and "due_date" in request.data
            ):
                raise PermissionDenied("Нельзя изменить дедлайн после оценивания")

            if new_status:
                if new_status == Assignment.Status.SUBMITTED:
                    raise PermissionDenied(
                        "Преподаватели не могут отмечать задания как сданные"
                    )

                if (
                    new_status == Assignment.Status.UNDER_REVIEW
                    and assignment.status != Assignment.Status.SUBMITTED
                ):
                    raise PermissionDenied(
                        "Перевести на проверку можно только после сдачи"
                    )

                if new_status == Assignment.Status.GRADED:
                    if assignment.status != Assignment.Status.UNDER_REVIEW:
                        raise PermissionDenied(
                            "Поставить оценку можно только после проверки"
                        )
                    grade_val = request.data.get("grade")
                    if grade_val is None:
                        raise PermissionDenied("Требуется поле grade (1-12)")
                    try:
                        grade_int = int(grade_val)
                    except (TypeError, ValueError):
                        raise PermissionDenied("grade должен быть числом от 1 до 12")
                    if not (1 <= grade_int <= 12):
                        raise PermissionDenied("grade должен быть числом от 1 до 12")

                if (
                    new_status == Assignment.Status.REVOKED
                    and assignment.status == Assignment.Status.REVOKED
                ):
                    raise PermissionDenied("Задание уже отозвано")

                if (
                    assignment.status == Assignment.Status.GRADED
                    and new_status != Assignment.Status.REVOKED
                ):
                    raise PermissionDenied(
                        "Оценённое задание можно только отозвать"
                    )

                if new_status != Assignment.Status.GRADED:
                    if "grade" in request.data or "feedback" in request.data:
                        raise PermissionDenied(
                            "grade можно задать только при выставлении статуса GRADED, "
                            "feedback — только при выставлении grade"
                        )
            else:
                if "grade" in request.data:
                    raise PermissionDenied(
                        "grade можно задать только при выставлении статуса GRADED"
                    )
        else:
            raise PermissionDenied("Хм. Вы и не препод и не студент.. Как так..")

        return super().update(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)


class LessonViewSet(viewsets.ModelViewSet):
    serializer_class = LessonSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        teacher = TeacherProfile.objects.filter(user=user).first()
        if teacher:
            return Lesson.objects.filter(teacher=teacher)
        student = StudentProfile.objects.filter(user=user).first()
        if student and student.group.pk:
            return Lesson.objects.filter(group_id=student.group.pk)
        return Lesson.objects.none()

    def get_serializer_class(self):
        if self.action == "create":
            return LessonCreateSerializer
        return LessonSerializer

    def perform_create(self, serializer):
        teacher = TeacherProfile.objects.filter(user=self.request.user).first()
        if not teacher:
            raise PermissionDenied("Создавать уроки могут только преподаватели")

        validated = serializer.validated_data
        group = validated.get("group")
        group_teacher = getattr(group, "teacher", None)


class ScheduleView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from datetime import datetime, timedelta
        from django.utils import timezone

        week_start_str = request.query_params.get("week_start")
        if week_start_str:
            try:
                week_start = datetime.strptime(week_start_str, "%Y-%m-%d").date()
            except ValueError:
                return Response({"detail": "Некорректный формат даты"}, status=400)
        else:
            today = timezone.now().date()
            week_start = today - timedelta(days=today.weekday())

        week_end = week_start + timedelta(days=6)

        user = request.user
        teacher = TeacherProfile.objects.filter(user=user).first()
        student = StudentProfile.objects.filter(user=user).first()

        lessons = Lesson.objects.none()

        if teacher:
            lessons = Lesson.objects.filter(teacher=teacher, date__range=[week_start, week_end])
        elif student and student.group:
            lessons = Lesson.objects.filter(group=student.group, date__range=[week_start, week_end])

        serializer = LessonSerializer(lessons, many=True)
        lessons_data = serializer.data

        if student:
            lesson_ids = [lesson['id'] for lesson in lessons_data]
            attendances = Attendance.objects.filter(
                lesson_id__in=lesson_ids,
                student=student
            ).select_related('lesson')

            attendance_map = {att.lesson_id: att for att in attendances}

            for lesson in lessons_data:
                attendance = attendance_map.get(lesson['id'])
                lesson['attendance_grade'] = attendance.grade if attendance else None

        return Response({
            "week_start": week_start.strftime("%Y-%m-%d"),
            "week_end": week_end.strftime("%Y-%m-%d"),
            "lessons": lessons_data
        })


class TeacherStudentsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        teacher = TeacherProfile.objects.filter(user=request.user).first()
        if not teacher:
            return Response({"detail": "Только преподаватели могут просматривать учеников"}, status=403)

        groups = teacher.groups.all()
        students = StudentProfile.objects.filter(group__in=groups).select_related('user', 'group')

        students_data = []
        for student in students:
            students_data.append({
                "id": student.id,
                "username": student.user.username,
                "first_name": student.user.first_name,
                "last_name": student.user.last_name,
                "group": student.group.name if student.group else None,
                "xp": student.xp,
                "level": student.level,
                "crystals": student.crystals,
            })

        return Response({"students": students_data})


class StudentAssignmentsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, student_id):
        teacher = TeacherProfile.objects.filter(user=request.user).first()
        if not teacher:
            return Response({"detail": "Только преподаватели могут просматривать задания учеников"}, status=403)

        student = StudentProfile.objects.filter(id=student_id).first()
        if not student:
            return Response({"detail": "Ученик не найден"}, status=404)

        if not student.group or not teacher.groups.filter(pk=student.group.pk).exists():
            return Response({"detail": "Ученик не в вашей группе"}, status=403)

        assignments = Assignment.objects.filter(group=student.group).exclude(
            status=Assignment.Status.REVOKED
        )

        assignments_data = []
        for assignment in assignments:
            assignments_data.append({
                "id": assignment.id,
                "title": assignment.title,
                "description": assignment.description,
                "due_date": assignment.due_date,
                "status": assignment.status,
                "answer": assignment.answer,
                "grade": assignment.grade,
                "feedback": assignment.feedback,
                "created_at": assignment.created_at,
            })

        return Response({"student_id": student.id, "student_name": f"{student.user.first_name} {student.user.last_name}", "assignments": assignments_data})


class GradeAssignmentView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, student_id, assignment_id):
        teacher = TeacherProfile.objects.filter(user=request.user).first()
        if not teacher:
            return Response({"detail": "Только преподаватели могут оценивать задания"}, status=403)

        student = StudentProfile.objects.filter(id=student_id).first()
        if not student:
            return Response({"detail": "Ученик не найден"}, status=404)

        if not student.group or not teacher.groups.filter(pk=student.group.pk).exists():
            return Response({"detail": "Ученик не в вашей группе"}, status=403)

        assignment = Assignment.objects.filter(id=assignment_id, group=student.group).first()
        if not assignment:
            return Response({"detail": "Задание не найдено"}, status=404)

        grade = request.data.get("grade")
        feedback = request.data.get("feedback")

        if grade is not None:
            try:
                grade = int(grade)
                if grade < 1 or grade > 12:
                    return Response({"detail": "Оценка должна быть от 1 до 12"}, status=400)
            except (ValueError, TypeError):
                return Response({"detail": "Оценка должна быть числом"}, status=400)

        assignment.grade = grade
        assignment.feedback = feedback
        
        if grade is not None:
            assignment.status = Assignment.Status.GRADED
            if assignment.subject:
                from api.models import Grade
                Grade.objects.create(
                    student=student,
                    subject=assignment.subject,
                    value=grade
                )
        
        assignment.save()
        if grade is not None:
            create_notification(
        recipient=student.user,
        notification_type='assignment_graded',
        title=f'Оценка за задание "{assignment.title}"',
        message=f'Вы получили оценку {grade}. {feedback or ""}',
        sender=request.user,
        link=f'/assignments/{assignment.id}'
    )

        return Response({
            "id": assignment.id,
            "grade": assignment.grade,
            "feedback": assignment.feedback,
            "status": assignment.status
        })


class CurrentLessonView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        teacher = TeacherProfile.objects.filter(user=request.user).first()
        if not teacher:
            return Response({"detail": "Только преподаватели могут просматривать текущий урок"}, status=403)

        from django.utils import timezone

        now = timezone.now()
        current_date = now.date()

        today_lessons = Lesson.objects.filter(
            teacher=teacher,
            date=current_date
        ).order_by('start_time')

        lessons_data = []
        for lesson in today_lessons:
            lessons_data.append({
                "id": lesson.id,
                "subject": lesson.subject,
                "start_time": lesson.start_time.strftime("%H:%M"),
                "end_time": lesson.end_time.strftime("%H:%M"),
                "room": lesson.room,
                "group": {
                    "id": lesson.group.id,
                    "name": lesson.group.name
                },
                "date": lesson.date.strftime("%Y-%m-%d")
            })

        return Response({
            "current_lesson": None,
            "today_lessons": lessons_data,
            "message": "Выберите урок из списка на сегодня."
        })


class StudentStatisticsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        student = StudentProfile.objects.filter(user=request.user).first()
        if not student:
            return Response({"detail": "Только ученики могут просматривать статистику"}, status=403)

        statistics, created = StudentStatistics.objects.get_or_create(
            student=student,
            defaults={
                'rank': 0,
                'completed_assignments': 0,
                'incomplete_assignments': 0,
                'total_xp': student.xp
            }
        )

        if student.group:
            completed_count = Assignment.objects.filter(
                group=student.group,
                status__in=[Assignment.Status.SUBMITTED, Assignment.Status.GRADED]
            ).count()

            incomplete_count = Assignment.objects.filter(
                group=student.group,
                status=Assignment.Status.ISSUED
            ).filter(due_date__gte=now).count()

            group_students = StudentProfile.objects.filter(group=student.group).order_by('-xp')
            rank = list(group_students).index(student) + 1 if student in group_students else 0

            statistics.completed_assignments = completed_count
            statistics.incomplete_assignments = incomplete_count
            statistics.rank = rank
            statistics.total_xp = student.xp
            statistics.save()

            self._calculate_monthly_grades(student)

        serializer = StudentStatisticsSerializer(statistics)
        return Response(serializer.data)

    def _calculate_monthly_grades(self, student):
        """Calculate and store average grades for each month"""
        from django.db.models import Avg
        from datetime import datetime, timedelta

        attendances = Attendance.objects.filter(
            student=student,
            grade__isnull=False
        ).select_related('lesson')

        monthly_data = {}
        for attendance in attendances:
            lesson_date = attendance.lesson.date
            year = lesson_date.year
            month = lesson_date.month
            key = (year, month)

            if key not in monthly_data:
                monthly_data[key] = []
            monthly_data[key].append(attendance.grade)

        for (year, month), grades in monthly_data.items():
            avg_grade = sum(grades) / len(grades)
            MonthlyAverageGrade.objects.update_or_create(
                student=student,
                year=year,
                month=month,
                defaults={'average_grade': avg_grade}
            )


class GroupLeaderboardView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        student = StudentProfile.objects.filter(user=request.user).first()
        if not student or not student.group:
            return Response({"detail": "Только ученики в группе могут просматривать лидерборд"}, status=403)

        group_students = StudentProfile.objects.filter(group=student.group).order_by('-xp')
        
        leaderboard_data = []
        for idx, student_profile in enumerate(group_students, start=1):
            stats, _ = StudentStatistics.objects.get_or_create(
                student=student_profile,
                defaults={
                    'rank': idx,
                    'completed_assignments': 0,
                    'incomplete_assignments': 0,
                    'total_xp': student_profile.xp
                }
            )
            
            stats.rank = idx
            stats.save()
            
            leaderboard_data.append({
                'rank': idx,
                'student_id': student_profile.id,
                'username': student_profile.user.username,
                'first_name': student_profile.user.first_name,
                'last_name': student_profile.user.last_name,
                'xp': student_profile.xp,
                'completed_assignments': stats.completed_assignments,
                'incomplete_assignments': stats.incomplete_assignments,
                'is_current_user': student_profile.user == request.user
            })
        
        return Response({
            'group_name': student.group.name,
            'leaderboard': leaderboard_data
        })


class MonthlyGradesView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        student = StudentProfile.objects.filter(user=request.user).first()
        if not student:
            return Response({"detail": "Только ученики могут просматривать оценки"}, status=403)

        from datetime import datetime, timedelta
        from django.utils import timezone

        now = timezone.now()
        monthly_grades = MonthlyAverageGrade.objects.filter(
            student=student
        ).order_by('-year', '-month')[:6]

        labels = []
        data = []
        for grade in reversed(list(monthly_grades)):
            month_names = ['Янв', 'Фев', 'Мар', 'Апр', 'Май', 'Июн', 
                          'Июл', 'Авг', 'Сен', 'Окт', 'Ноя', 'Дек']
            labels.append(f"{month_names[grade.month - 1]} {grade.year}")
            data.append(round(grade.average_grade, 2))

        return Response({
            'labels': labels,
            'data': data
        })


class LessonViewSet(viewsets.ModelViewSet):
    serializer_class = LessonSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        teacher = TeacherProfile.objects.filter(user=user).first()
        if teacher:
            return Lesson.objects.filter(teacher=teacher)
        student = StudentProfile.objects.filter(user=user).first()
        if student and student.group.pk:
            return Lesson.objects.filter(group_id=student.group.pk)
        return Lesson.objects.none()

    def get_serializer_class(self):
        if self.action == "create":
            return LessonCreateSerializer
        return LessonSerializer

    def perform_create(self, serializer):
        teacher = TeacherProfile.objects.filter(user=self.request.user).first()
        if not teacher:
            raise PermissionDenied("Создавать уроки могут только преподаватели")

        validated = serializer.validated_data
        group = validated.get("group")
        group_teacher = getattr(group, "teacher", None)
        if group_teacher != teacher:
            raise PermissionDenied("Невозможно поставить урок не в свою группу")

        serializer.save(teacher=teacher)

    def perform_update(self, serializer):
        lesson = self.get_object()
        teacher = TeacherProfile.objects.filter(user=self.request.user).first()
        if not teacher:
            raise PermissionDenied("Изменять уроки могут только преподаватели")
        if lesson.teacher != teacher:
            raise PermissionDenied("Вы можете редактировать только свои уроки")

        validated = serializer.validated_data
        group = validated.get("group", lesson.group)
        group_teacher = getattr(group, "teacher", None)
        if group_teacher != teacher:
            raise PermissionDenied("Невозможно перевести урок в группу другого преподавателя")

        serializer.save()

    def perform_destroy(self, instance):
        teacher = TeacherProfile.objects.filter(user=self.request.user).first()
        if not teacher or instance.teacher != teacher:
            raise PermissionDenied("Вы можете удалять только свои уроки")
        super().perform_destroy(instance)


class StudentAssignmentFeedView(generics.ListAPIView):
    serializer_class = AssignmentSerializer
    permission_classes = [IsAuthenticated, IsStudent]

    def get_queryset(self):
        student = StudentProfile.objects.get(user=self.request.user)
        if not student.group:
            return Assignment.objects.none()
        return Assignment.objects.filter(group=student.group).exclude(
            status=Assignment.Status.REVOKED
        )


class TeacherAssignmentFeedView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        teacher = TeacherProfile.objects.filter(user=request.user).first()
        if not teacher:
            return Response({"detail": "Только преподаватели могут просматривать задания для оценки"}, status=403)

        groups = teacher.groups.all()
        assignments = Assignment.objects.filter(group__in=groups).exclude(
            status=Assignment.Status.REVOKED
        ).select_related('group', 'teacher')

        assignments_data = []
        for assignment in assignments:
            assignments_data.append({
                "id": assignment.id,
                "title": assignment.title,
                "description": assignment.description,
                "due_date": assignment.due_date,
                "status": assignment.status,
                "effective_status": assignment.effective_status,
                "answer": assignment.answer,
                "grade": assignment.grade,
                "feedback": assignment.feedback,
                "group": assignment.group.name,
                "teacher": assignment.teacher.user.username if assignment.teacher else None,
                "created_at": assignment.created_at,
            })

        return Response(assignments_data)


class GroupInviteCodeView(APIView):
    permission_classes = [IsAuthenticated, IsTeacher]

    def post(self, request):
        teacher = TeacherProfile.objects.filter(user=request.user).first()
        if not teacher:
            raise PermissionDenied("Только преподы могут получать коды")

        group_id = request.data.get("group_id")
        if not group_id:
            return Response({"detail": "Необходим group_id"}, status=400)

        try:
            group = Group.objects.get(pk=group_id)
        except Group.DoesNotExist:
            return Response({"detail": "Такая группа не существует"}, status=404)

        if not group.teachers.filter(pk=teacher.pk).exists():
            raise PermissionDenied("Вы не владеете этой группой")

        max_uses = int(request.data.get("max_uses", 1))
        ttl_minutes = int(request.data.get("ttl_minutes", 1440))

        if max_uses < 1:
            return Response({"detail": "max_uses должен быть >= 1 (больше или равно)"}, status=400)
        if ttl_minutes < 1:
            return Response({"detail": "ttl_minutes должен быть >= 1 (больше или равно)"}, status=400)

        import secrets
        code = secrets.token_hex(4).upper()
        obj = GroupInviteCode.objects.create(
            code=code,
            group=group,
            teacher=teacher,
            max_uses=max_uses,
            ttl_minutes=ttl_minutes,
        )

        return Response({
            "code": obj.code,
            "group_id": group.pk,
            "group_name": group.name,
            "max_uses": obj.max_uses,
            "ttl_minutes": obj.ttl_minutes,
            "expires_at": obj.expires_at.isoformat(),
        })


class StudentJoinGroupView(APIView):
    permission_classes = [IsAuthenticated, IsStudent]

    def post(self, request):
        student = StudentProfile.objects.get(user=request.user)
        code = request.data.get("code")
        if not code:
            return Response({"detail": "Необходим код"}, status=400)

        try:
            invite = GroupInviteCode.objects.get(code=code)
        except GroupInviteCode.DoesNotExist:
            return Response({"detail": "Некорректный инвайткод"}, status=404)

        if not invite.is_valid():
            return Response({"detail": "Инвайткод устарел"}, status=400)

        invite.use(student)
        return Response({
            "student_id": student.pk,
            "group_id": invite.group.pk,
            "group_name": invite.group.name,
        })


class GenerateTeacherInviteCodeView(APIView):
    permission_classes = [IsAuthenticated, IsAdmin]

    def post(self, request):
        code = secrets.token_hex(4).upper()
        obj = TeacherInviteCode.objects.create(code=code, is_active=True)
        return Response({
            "code": obj.code,
            "expires_in_minutes": obj.ttl_minutes,
        })

@api_view(['GET'])
def trigger_error_view(request):
    bad_calc = 1 / 0 
    return JsonResponse({"message": "something"})



class LessonAttendanceView(APIView):
    permission_classes = [IsAuthenticated, IsTeacher]

    def get_lesson_and_check_access(self, lesson_id):
        lesson = get_object_or_404(Lesson, pk=lesson_id)
        teacher = TeacherProfile.objects.filter(user=self.request.user).first()
        if not teacher:
            raise PermissionDenied("Только преподаватели могут работать с посещаемостью")
        if not teacher.groups.filter(pk=lesson.group_id).exists():
            raise PermissionDenied("Вы не ведёте группу этого урока")
        return lesson

    def get(self, request, lesson_id):
        """
        Возвращает список студентов группы урока с отметкой о присутствии.
        Для студентов, у которых ещё нет записи Attendance, создаётся со значением is_present=False.
        """
        lesson = self.get_lesson_and_check_access(lesson_id)
        students = StudentProfile.objects.filter(group=lesson.group)

        with transaction.atomic():
            for student in students:
                Attendance.objects.get_or_create(
                    lesson=lesson,
                    student=student,
                    defaults={'is_present': False}
                )

        attendances = Attendance.objects.filter(lesson=lesson).select_related('student__user')
        serializer = AttendanceSerializer(attendances, many=True)
        return Response(serializer.data)

    def post(self, request, lesson_id):
        """
        Принимает список объектов: [{"student_id": 1, "is_present": true, "grade": 5, "crystals_awarded": 2}, ...]
        Обновляет посещаемость, оценки и кристаллы.
        """
        lesson = self.get_lesson_and_check_access(lesson_id)
        attendance_data = request.data

        if not isinstance(attendance_data, list):
            return Response({"detail": "Ожидается список объектов посещаемости"}, status=status.HTTP_400_BAD_REQUEST)

        updated = []
        errors = []

        with transaction.atomic():
            for item in attendance_data:
                student_id = item.get('student_id')
                is_present = item.get('is_present', False)
                grade = item.get('grade')
                crystals_awarded = item.get('crystals_awarded', 0)

                if student_id is None:
                    errors.append({"item": item, "error": "student_id обязателен"})
                    continue

                if grade is not None:
                    try:
                        grade = int(grade)
                        if grade < 1 or grade > 12:
                            errors.append({"student_id": student_id, "error": "Оценка должна быть от 1 до 12"})
                            continue
                    except (ValueError, TypeError):
                        errors.append({"student_id": student_id, "error": "Оценка должна быть числом"})
                        continue

                if crystals_awarded is not None:
                    try:
                        crystals_awarded = int(crystals_awarded)
                        if crystals_awarded < 0 or crystals_awarded > 3:
                            errors.append({"student_id": student_id, "error": "Кристаллы должны быть от 0 до 3"})
                            continue
                    except (ValueError, TypeError):
                        errors.append({"student_id": student_id, "error": "Кристаллы должны быть числом"})
                        continue

                try:
                    student = StudentProfile.objects.select_for_update().get(pk=student_id, group=lesson.group)
                except StudentProfile.DoesNotExist:
                    errors.append({"student_id": student_id, "error": "Студент не найден или не в этой группе"})
                    continue

                attendance, created = Attendance.objects.get_or_create(
                    lesson=lesson,
                    student=student,
                    defaults={'is_present': is_present}
                )

                if not created:
                    attendance.is_present = is_present
                    attendance.grade = grade
                    attendance.crystals_awarded = crystals_awarded
                    attendance.save(update_fields=['is_present', 'grade', 'crystals_awarded'])
                else:
                    attendance.grade = grade
                    attendance.crystals_awarded = crystals_awarded
                    attendance.save(update_fields=['grade', 'crystals_awarded'])

                if is_present and not attendance.crystals_granted:
                    student.crystals += 1
                    student.save(update_fields=['crystals'])
                    attendance.crystals_granted = True
                    attendance.save(update_fields=['crystals_granted'])

                if crystals_awarded > 0:
                    student.crystals += crystals_awarded
                    student.save(update_fields=['crystals'])

                updated.append(AttendanceSerializer(attendance).data)

        if grade is not None:
            create_notification(
            recipient=student.user,
            notification_type='lesson_graded',
            title=f'Оценка за урок {lesson.subject}',
            message=f'Вы получили оценку {grade}.',
            sender=request.user,
            link=f'/lessons/{lesson.id}'
        )
        elif is_present and not attendance.crystals_granted_before:
            create_notification(
            recipient=student.user,
            notification_type='attendance_marked',
            title=f'Отметка о посещении {lesson.subject}',
            message='Вы отмечены как присутствующий.',
            sender=request.user,
            link=f'/lessons/{lesson.id}'
        )
        response_status = status.HTTP_200_OK if not errors else status.HTTP_207_MULTI_STATUS
        return Response({
            "updated": updated,
            "errors": errors
        }, status=response_status)



class DailyQuestView(APIView):
    permission_classes = [IsAuthenticated, IsStudent]

    def get(self, request):
        try:
            student = request.user.studentprofile
        except StudentProfile.DoesNotExist:
            return Response([], status=status.HTTP_200_OK)
        
        generate_daily_quests(student)
        today = timezone.now().date()
        quests = StudentDailyQuest.objects.filter(student=student, date=today)
        data = []
        for sq in quests:
            data.append({
                'id': sq.id,
                'quest_type': sq.quest.quest_type,
                'target_value': sq.quest.target_value,
                'progress': sq.progress,
                'completed': sq.completed,
                'xp_reward': sq.quest.xp_reward,
                'crystal_reward': sq.quest.crystal_reward,
            })
        return Response(data)


class BadgeListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        badges = Badge.objects.all()
        data = []
        student = None
        if hasattr(request.user, 'studentprofile'):
            student = request.user.studentprofile
        for badge in badges:
            obtained = StudentBadge.objects.filter(student=student, badge=badge).exists() if student else False
            data.append({
                'id': badge.id,
                'name': badge.name,
                'description': badge.description,
                'obtained': obtained,
                'xp_reward': badge.xp_reward,
                'crystal_reward': badge.crystal_reward,
            })
        return Response(data)

class MyBadgeView(APIView):
    permission_classes = [IsAuthenticated, IsStudent]

    def get(self, request):
        try:
            student = request.user.studentprofile
        except StudentProfile.DoesNotExist:
            return Response([], status=status.HTTP_200_OK)
        
        obtained = StudentBadge.objects.filter(student=student).select_related('badge')
        data = [{
            'id': sb.id,
            'badge_name': sb.badge.name,
            'description': sb.badge.description,
            'obtained_at': sb.created_at
        } for sb in obtained]
        return Response(data)



class LevelRewardListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        rewards = LevelReward.objects.all()
        student = None
        if hasattr(request.user, 'studentprofile'):
            student = request.user.studentprofile
        data = []
        for reward in rewards:
            obtained = student and student.level >= reward.level if student else False
            data.append({
                'level': reward.level,
                'crystals_bonus': reward.crystals_bonus,
                'badge': reward.badge.name if reward.badge else None,
                'obtained': obtained,
            })
        return Response(data)


class RouletteView(APIView):
    permission_classes = [IsAuthenticated, IsStudent]

    def post(self, request):
        student = StudentProfile.objects.get(user=request.user)
        amount = request.data.get('amount')
        choice = request.data.get('choice')

        # Валидация
        if not amount or not choice:
            return Response({"error": "Укажите amount и choice (red/black/green)"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            amount = int(amount)
            if amount <= 0:
                raise ValueError
        except (ValueError, TypeError):
            return Response({"error": "Сумма ставки должна быть положительным целым числом"}, status=status.HTTP_400_BAD_REQUEST)

        if choice not in ['red', 'black', 'green']:
            return Response({"error": "choice должен быть 'red', 'black' или 'green'"}, status=status.HTTP_400_BAD_REQUEST)

        if student.crystals < amount:
            return Response({"error": "Недостаточно кристаллов"}, status=status.HTTP_400_BAD_REQUEST)

        colors = ['red', 'black', 'green']
        weights = [18/37, 18/37, 1/37]
        result_color = random.choices(colors, weights=weights, k=1)[0]
        if choice == result_color:
            if result_color == 'green':
                multiplier = 5
            else:
                multiplier = 2
            win = True
            win_amount = amount * multiplier
        else:
            win = False
            win_amount = 0

        with transaction.atomic():
            student = StudentProfile.objects.select_for_update().get(pk=student.pk)         
            student.crystals -= amount
            if win:
                student.crystals += win_amount
            student.save(update_fields=['crystals'])

            bet = RouletteBet.objects.create(
                student=student,
                amount=amount,
                choice=choice,
                result_color=result_color,
                win=win
            )

        return Response({
            "result": result_color,
            "win": win,
            "win_amount": win_amount if win else 0,
            "new_balance": student.crystals
        })

    def get(self, request):
        student = StudentProfile.objects.get(user=request.user)
        bets = RouletteBet.objects.filter(student=student).order_by('-created_at')[:20]
        history = []
        for bet in bets:
            history.append({
                "id": bet.id,
                "amount": bet.amount,
                "choice": bet.choice,
                "result_color": bet.result_color,
                "win": bet.win,
                "created_at": bet.created_at.isoformat()
            })
        return Response(history)
