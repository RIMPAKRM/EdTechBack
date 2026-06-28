from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.utils import timezone
from django.contrib.auth.signals import user_logged_in
from api.models import (
    StudentProfile, Grade, XPEvent, Assignment, Attendance,
    StudentDailyQuest, DailyQuest, StudentBadge, Badge, Purchase
)
from .utils import update_daily_quests, check_and_award_badges

@receiver(post_delete, sender=StudentProfile)
def delete_avatar_on_profile_delete(sender, instance, **kwargs):
    try:
        if instance.avatar:
            storage = instance._meta.get_field("avatar").storage
            if storage.exists(instance.avatar.name):
                storage.delete(instance.avatar.name)
    except Exception:
        pass

@receiver(post_save, sender=Grade)
def add_xp_from_grade(sender, instance, created, **kwargs):
    if not created:
        return
    xp_gain = instance.value * 2
    instance.student.add_xp(xp_gain, f"Оценка по предмету {instance.subject.name}")

@receiver(user_logged_in)
def daily_login_bonus(sender, request, user, **kwargs):
    try:
        student = user.studentprofile
    except StudentProfile.DoesNotExist:
        return

    today = timezone.now().date()
    if not XPEvent.objects.filter(
        student=student,
        reason="Ежедневный вход",
        created_at__date=today
    ).exists():
        student.add_xp(10, "Ежедневный вход")
        student.crystals += 1
        student.save(update_fields=['crystals'])

    update_daily_quests(student, 'login')
    check_and_award_badges(student)

@receiver(post_save, sender=Assignment)
def on_assignment_submitted(sender, instance, created, **kwargs):
    if created:
        return
    pass

@receiver(post_save, sender=Attendance)
def on_attendance_saved(sender, instance, created, **kwargs):
    student = instance.student
    reason = f"Посещение урока #{instance.lesson_id}"
    if instance.is_present and not XPEvent.objects.filter(student=student, reason=reason).exists():
        student.add_xp(5, reason)
        update_daily_quests(student, 'attend_lesson')
        check_and_award_badges(student)

@receiver(post_save, sender=Purchase)
def on_purchase_created(sender, instance, created, **kwargs):
    if created and instance.status == 'pending':
        student = instance.student
        update_daily_quests(student, 'buy_item')
        check_and_award_badges(student)
