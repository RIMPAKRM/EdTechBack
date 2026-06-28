from django.db import models, transaction
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta
from io import BytesIO
from django.core.validators import MinValueValidator, MaxValueValidator
from rest_framework.response import Response
from django.utils.crypto import get_random_string
from django.core.files.base import ContentFile
from PIL import Image, ImageOps


WEEKDAY_CHOICES = (
    (0, "Понедельник"),
    (1, "Вторник"),
    (2, "Среда"),
    (3, "Четверг"),
    (4, "Пятница"),
    (5, "Суббота"),
    (6, "Воскресенье"),
)


class Lesson(models.Model):
    group = models.ForeignKey("Group", on_delete=models.CASCADE, related_name="lessons")
    subject = models.CharField(max_length=128)
    teacher = models.CharField(max_length=128)
    date = models.DateField(null=True, blank=True)
    start_time = models.TimeField()
    end_time = models.TimeField()
    room = models.CharField(max_length=64, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["date", "start_time"]

    def __str__(self):
        return f"{self.group.name} — {self.subject} ({self.date})"

class Group(models.Model):
    name = models.CharField(max_length=128)
    teachers = models.ManyToManyField("TeacherProfile", related_name="groups", blank=True)

    def __str__(self):
        return self.name


class StudentProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    xp = models.IntegerField(default=0)
    level = models.IntegerField(default=1)
    group = models.ForeignKey(Group, on_delete=models.SET_NULL, null=True, blank=True, related_name="students")
    crystals = models.IntegerField(default=0)
    avatar = models.ImageField(upload_to="avatars/", null=True, blank=True)

    def __str__(self):
        return self.user.username


    def add_xp(self, amount, reason):
        """Централизованное начисление XP с проверкой повышения уровня."""
        with transaction.atomic():
            self.xp += amount
            old_level = self.level
            self.level = max(1, (self.xp // 100) + 1)
            self.save(update_fields=['xp', 'level'])

            XPEvent.objects.create(student=self, amount=amount, reason=reason)

            if self.level > old_level:
                self._on_level_up(old_level, self.level)

    def _on_level_up(self, old_level, new_level):
        """Обработка получения нового уровня: награды за каждый пройденный уровень."""
        for level in range(old_level + 1, new_level + 1):
            try:
                reward = LevelReward.objects.get(level=level)
                if reward.crystals_bonus:
                    self.crystals += reward.crystals_bonus
                    self.save(update_fields=['crystals'])
                if reward.badge:
                    StudentBadge.objects.get_or_create(student=self, badge=reward.badge)
                XPEvent.objects.create(
                    student=self,
                    amount=0,
                    reason=f"Достижение уровня {level}: {reward.description or ''}"
                )
            except LevelReward.DoesNotExist:
                pass
        create_notification(
            recipient=self.user,
            notification_type='level_up',
            title=f'Новый уровень {new_level}!',
            message=f'Поздравляем! Вы достигли {new_level} уровня.',
            link='/profile'
        )


    def save(self, *args, **kwargs):
        if self.pk:
            try:
                old = StudentProfile.objects.get(pk=self.pk)
                if old.xp != self.xp:
                    self.level = max(1, (self.xp // 100) + 1)
            except StudentProfile.DoesNotExist:
                pass

        old_avatar_name = None
        if self.pk:
            try:
                old = StudentProfile.objects.get(pk=self.pk)
                old_avatar_name = old.avatar.name if old.avatar else None
            except StudentProfile.DoesNotExist:
                old_avatar_name = None

        if self.avatar:
            try:
                self.avatar.open()
            except FileNotFoundError:
                pass
            except Exception:
                pass
            else:
                try:
                    img = Image.open(self.avatar)
                    img = img.convert("RGB")
                    size = (256, 256)
                    img = ImageOps.fit(img, size, Image.Resampling.LANCZOS)
                    buf = BytesIO()
                    img.save(buf, format="AVIF", quality=85, optimize=True)
                    buf.seek(0)
                    filename = f"{self.user.pk}_{int(timezone.now().timestamp())}.avif"
                    self.avatar.save(filename, ContentFile(buf.read()), save=False)
                except Exception:
                    pass

        super().save(*args, **kwargs)

        try:
            if old_avatar_name and old_avatar_name != (self.avatar.name if self.avatar else None):
                storage = self.avatar.storage
                if storage.exists(old_avatar_name):
                    storage.delete(old_avatar_name)
        except Exception:
            pass


class TeacherProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    avatar = models.ImageField(upload_to="avatars/", null=True, blank=True)

    def save(self, *args, **kwargs):
        old_avatar_name = None
        if self.pk:
            try:
                old = TeacherProfile.objects.get(pk=self.pk)
                old_avatar_name = old.avatar.name if old.avatar else None
            except TeacherProfile.DoesNotExist:
                old_avatar_name = None

        if self.avatar and hasattr(self.avatar, "file"):
            try:
                self.avatar.open()
                img = Image.open(self.avatar)
                img = img.convert("RGB")

                size = (256, 256)
                img = ImageOps.fit(img, size, Image.Resampling.LANCZOS)

                buf = BytesIO()
                img.save(buf, format="AVIF", quality=85, optimize=True)
                buf.seek(0)

                filename = f"{self.user.pk}_{int(timezone.now().timestamp())}.avif"

                self.avatar.save(filename, ContentFile(buf.read()), save=False)
            except Exception:
                pass

        super().save(*args, **kwargs)

        try:
            if old_avatar_name and old_avatar_name != (
                self.avatar.name if self.avatar else None
            ):
                storage = self.avatar.storage
                if storage.exists(old_avatar_name):
                    storage.delete(old_avatar_name)
        except Exception:
            pass

    def __str__(self):
        return self.user.username

class Subject(models.Model):
    name = models.CharField(max_length=128, unique=True)

    def __str__(self):
        return self.name


class Assignment(models.Model):

    class Status(models.TextChoices):
        ISSUED = "issued", "Issued"
        SUBMITTED = "submitted", "Submitted"
        UNDER_REVIEW = "under_review", "Under Review"
        GRADED = "graded", "Graded"
        REVOKED = "revoked", "Revoked"

    title = models.CharField(max_length=256)
    description = models.TextField(blank=True)
    answer = models.CharField(max_length=4096, blank=True, default="")
    grade = models.IntegerField(
        null=True, blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(12)]
    )
    feedback = models.TextField(max_length=4096, blank=True, default="")

    teacher = models.ForeignKey(TeacherProfile, on_delete=models.CASCADE, related_name="assignments")
    group = models.ForeignKey(Group, on_delete=models.CASCADE, related_name="assignments")

    status = models.CharField(max_length=32, choices=Status.choices, default=Status.ISSUED)
    created_at = models.DateTimeField(auto_now_add=True)
    due_date = models.DateTimeField(null=True, blank=True)
    subject = models.ForeignKey(Subject, null=True, blank=True, on_delete=models.SET_NULL, related_name='assignments')
    def save(self, *args, **kwargs):
        if not self.due_date:
            self.due_date = timezone.now() + timedelta(days=7)
        super().save(*args, **kwargs)

    @property
    def effective_status(self):
        if self.status == self.Status.ISSUED and self.due_date and timezone.now() > self.due_date:
            return "overdue"
        return self.status


class TeacherInviteCode(models.Model):
    code = models.CharField(max_length=64, unique=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    max_uses = models.IntegerField(default=1)
    used_count = models.IntegerField(default=0)
    ttl_minutes = models.IntegerField(default=10)
    expires_at = models.DateTimeField(null=True, blank=True)

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.max_uses < 1:
            raise ValidationError("max_uses должно быть >= 1 (больше или равно)")
        if self.ttl_minutes < 1:
            raise ValidationError("ttl_minutes должно быть >= 1 (больше или равно)")

    def save(self, *args, **kwargs):
        self.clean()
        if not self.expires_at:
            self.expires_at = timezone.now() + timedelta(minutes=self.ttl_minutes)
        super().save(*args, **kwargs)

    def is_valid(self):
        return (
            self.is_active
            and self.used_count < self.max_uses
            and timezone.now() <= self.expires_at
        )

    def use(self):
        if not self.is_valid():
            raise ValueError("Инвайткод не валидный")
        self.used_count += 1
        if self.used_count >= self.max_uses:
            self.is_active = False
        self.save()


class Attendance(models.Model):
    student = models.ForeignKey(StudentProfile, on_delete=models.CASCADE, related_name="attendance")
    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name="attendance", null=True, blank=True)
    group = models.ForeignKey(Group, on_delete=models.CASCADE, related_name="attendance")
    is_present = models.BooleanField(default=False)
    grade = models.IntegerField(null=True, blank=True, validators=[MinValueValidator(1), MaxValueValidator(12)])
    crystals_awarded = models.IntegerField(default=0, validators=[MinValueValidator(0), MaxValueValidator(3)])
    date = models.DateField(auto_now_add=True)
    created_at = models.DateTimeField(auto_now_add=True)
    xp_granted = models.BooleanField(default=False)  

    class Meta:
        unique_together = ['student', 'lesson', 'date']
        ordering = ['student__user__last_name', 'student__user__first_name']

    def __str__(self):
        return f"{self.student.user.username} - {self.group.name} - {self.date}"


class GroupInviteCode(models.Model):
    code = models.CharField(max_length=64, unique=True)
    group = models.ForeignKey(Group, on_delete=models.CASCADE, related_name="invite_codes")
    teacher = models.ForeignKey(TeacherProfile, on_delete=models.CASCADE, related_name="group_invite_codes")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    max_uses = models.IntegerField(default=1)
    used_count = models.IntegerField(default=0)
    ttl_minutes = models.IntegerField(default=1440)
    expires_at = models.DateTimeField(null=True, blank=True)

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.max_uses < 1:
            raise ValidationError("max_uses должно быть >= 1 (больше или равно)")
        if self.ttl_minutes < 1:
            raise ValidationError("ttl_minutes должно быть >= 1 (больше или равно)")

    def save(self, *args, **kwargs):
        self.clean()
        if not self.expires_at:
            self.expires_at = timezone.now() + timedelta(minutes=self.ttl_minutes)
        super().save(*args, **kwargs)

        if self.is_valid():
            self.is_active = True

    def is_valid(self):
        return (
            self.is_active
            and self.used_count < self.max_uses
            and timezone.now() <= self.expires_at
        )

    def use(self, student):
        if not self.is_valid():
            raise ValueError("Инвайткод группы не действителен")
        if not self.group.teachers.filter(pk=self.teacher.pk).exists():
            raise ValueError("Это не ваша группа!")
        self.used_count += 1
        if self.used_count >= self.max_uses:
            self.is_active = False
        self.save()
        student.group = self.group
        student.save()





class Grade(models.Model):
    student = models.ForeignKey(StudentProfile, on_delete=models.CASCADE)
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE)
    value = models.IntegerField()
    created_at = models.DateTimeField(auto_now_add=True)


class Badge(models.Model):
    name = models.CharField(max_length=128)
    description = models.TextField()
    CONDITION_TYPES = [
        ('lessons_attended', 'Посещено уроков'),
        ('assignments_submitted', 'Сдано заданий'),
        ('total_xp', 'Накоплено XP'),
        ('items_bought', 'Куплено товаров'),
    ]
    condition_type = models.CharField(max_length=32, choices=CONDITION_TYPES, null=True, blank=True)
    condition_value = models.PositiveIntegerField(null=True, blank=True)
    xp_reward = models.PositiveIntegerField(default=0)
    crystal_reward = models.PositiveIntegerField(default=0)

    def __str__(self):
        return self.name


class StudentBadge(models.Model):
    student = models.ForeignKey(StudentProfile, on_delete=models.CASCADE)
    badge = models.ForeignKey(Badge, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)


class XPEvent(models.Model):
    student = models.ForeignKey(StudentProfile, on_delete=models.CASCADE)
    amount = models.IntegerField()
    reason = models.CharField(max_length=256)
    created_at = models.DateTimeField(auto_now_add=True)


class ShopItem(models.Model):
    ITEM_TYPES = (
        ('decoration', 'Украшение'),
        ('other', 'Другое'),
        ('product', 'товар'),
    )
    required_level = models.PositiveIntegerField(default=1, verbose_name="Требуемый уровень")

    name = models.CharField(max_length=128, verbose_name="Название")
    description = models.TextField(blank=True, verbose_name="Описание")
    price = models.PositiveIntegerField(verbose_name="Цена в кристаллах")
    item_type = models.CharField(max_length=32, choices=ITEM_TYPES, default='other', verbose_name="Тип товара")
    image_url = models.image_url = models.URLField(max_length=500, null=True, blank=True, verbose_name="Ссылка на изображение",help_text="Вставьте URL картинки из интернета")
    validity_days = models.PositiveIntegerField(
        null=True, blank=True, 
        verbose_name="Срок действия (дней)",
        help_text="Оставьте пустым, если покупка бессрочная"
    )
    is_active = models.BooleanField(default=True, verbose_name="Доступен для покупки")

    class Meta:
        verbose_name = "Товар"
        verbose_name_plural = "Товары"

    def __str__(self):
        return f"{self.name} ({self.price} 💎)"


class Purchase(models.Model):
    STATUS_CHOICES = (
        ('pending', 'Ожидает получения'),
        ('received', 'Получено'),
        ('expired', 'Истёк срок'),
    )

    student = models.ForeignKey(StudentProfile, on_delete=models.CASCADE, related_name='purchases', verbose_name="Ученик")
    item = models.ForeignKey(ShopItem, on_delete=models.SET_NULL, null=True, verbose_name="Товар")
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default='pending', verbose_name="Статус")
    code = models.CharField(max_length=12, unique=True, editable=False, verbose_name="Код покупки")
    
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата покупки")
    activated_at = models.DateTimeField(null=True, blank=True, verbose_name="Дата активации")
    expires_at = models.DateTimeField(null=True, blank=True, verbose_name="Сгорает до")

    class Meta:
        verbose_name = "Покупка"
        verbose_name_plural = "Покупки"
        ordering = ['-created_at']

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = get_random_string(12, allowed_chars='ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789')
        
        if not self.pk and self.item and self.item.validity_days:
            self.expires_at = timezone.now() + timedelta(days=self.item.validity_days)
            
        super().save(*args, **kwargs)

    def check_expiration(self):
        """Проверяет и обновляет статус, если срок истёк"""
        if self.status == 'pending' and self.expires_at and timezone.now() > self.expires_at:
            self.status = 'expired'
            self.save(update_fields=['status'])
            return True
        return False

    def __str__(self):
        item_name = self.item.name if self.item else "Удалённый товар"
        return f"Покупка {self.code} ({item_name}) - {self.student.user.username}"


class Attendance(models.Model):
    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name='attendances')
    student = models.ForeignKey(StudentProfile, on_delete=models.CASCADE, related_name='attendances')
    is_present = models.BooleanField(default=False)
    crystals_granted = models.BooleanField(default=False)
    grade = models.IntegerField(null=True, blank=True, validators=[MinValueValidator(1), MaxValueValidator(12)])
    crystals_awarded = models.IntegerField(default=0, validators=[MinValueValidator(0), MaxValueValidator(3)])
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('lesson', 'student')
        ordering = ['student__user__last_name', 'student__user__first_name']

    def __str__(self):
        return f"{self.student} @ {self.lesson}"


class StudentStatistics(models.Model):
    student = models.OneToOneField(StudentProfile, on_delete=models.CASCADE, related_name='statistics')
    rank = models.IntegerField(default=0, help_text="Место среди учеников в группе")
    completed_assignments = models.IntegerField(default=0, help_text="Количество выполненных заданий")
    incomplete_assignments = models.IntegerField(default=0, help_text="Количество невыполненных заданий")
    total_xp = models.IntegerField(default=0, help_text="Общий опыт")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Статистика ученика"
        verbose_name_plural = "Статистика учеников"

    def __str__(self):
        return f"Статистика: {self.student.user.username} (Ранг: {self.rank})"


class MonthlyAverageGrade(models.Model):
    student = models.ForeignKey(StudentProfile, on_delete=models.CASCADE, related_name='monthly_grades')
    year = models.IntegerField()
    month = models.IntegerField()
    average_grade = models.FloatField()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Средняя оценка за месяц"
        verbose_name_plural = "Средние оценки за месяцы"
        unique_together = ['student', 'year', 'month']
        ordering = ['-year', '-month']

    def __str__(self):
        return f"{self.student.user.username} - {self.month}/{self.year}: {self.average_grade}"


class LevelReward(models.Model):
    level = models.PositiveIntegerField(unique=True)
    crystals_bonus = models.PositiveIntegerField(default=0)
    badge = models.ForeignKey('Badge', null=True, blank=True, on_delete=models.SET_NULL)
    description = models.CharField(max_length=255, blank=True)

    def __str__(self):
        return f"Level {self.level} reward"



class DailyQuest(models.Model):
    QUEST_TYPES = [
        ('login', 'Вход в систему'),
        ('attend_lesson', 'Посетить урок'),
        ('submit_assignment', 'Сдать задание'),
        ('buy_item', 'Купить товар'),
        ('earn_xp', 'Заработать N XP'),
    ]
    quest_type = models.CharField(max_length=32, choices=QUEST_TYPES)
    target_value = models.PositiveIntegerField(default=1)
    xp_reward = models.PositiveIntegerField(default=20)
    crystal_reward = models.PositiveIntegerField(default=1)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.get_quest_type_display()} x{self.target_value}"


class StudentDailyQuest(models.Model):
    student = models.ForeignKey(StudentProfile, on_delete=models.CASCADE)
    quest = models.ForeignKey(DailyQuest, on_delete=models.CASCADE)
    progress = models.PositiveIntegerField(default=0)
    completed = models.BooleanField(default=False)
    date = models.DateField(default=timezone.now)

    class Meta:
        unique_together = ('student', 'quest', 'date')

    def __str__(self):
        return f"{self.student.user.username} - {self.quest} ({self.date})"



class Notification(models.Model):
    NOTIFICATION_TYPES = [
        ('assignment_graded', 'Задание оценено'),
        ('assignment_submitted', 'Задание сдано'),
        ('lesson_graded', 'Оценка за урок'),
        ('new_assignment', 'Новое задание'),
        ('attendance_marked', 'Отметка о посещении'),
        ('level_up', 'Повышение уровня'),
        ('badge_earned', 'Получен значок'),
        ('crystals_awarded', 'Начислены кристаллы'),
    ]

    recipient = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    sender = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='sent_notifications')
    notification_type = models.CharField(max_length=32, choices=NOTIFICATION_TYPES)
    title = models.CharField(max_length=256)
    message = models.TextField()
    link = models.CharField(max_length=512, blank=True, help_text="Опциональная ссылка для перехода")
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.notification_type} для {self.recipient.username}"

class RouletteBet(models.Model):
    COLOR_CHOICES = [
        ('red', 'Красное'),
        ('black', 'Черное'),
        ('green', 'Зеленое'),
    ]
    student = models.ForeignKey(StudentProfile, on_delete=models.CASCADE, related_name='roulette_bets')
    amount = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    choice = models.CharField(max_length=5, choices=COLOR_CHOICES)
    result_color = models.CharField(max_length=5, choices=COLOR_CHOICES, null=True, blank=True)
    win = models.BooleanField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.student.user.username} ставит {self.amount} на {self.get_choice_display()}"
