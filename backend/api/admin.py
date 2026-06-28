from django.contrib import admin
from .models import ShopItem, Purchase, Subject, Lesson, Group, TeacherInviteCode, GroupInviteCode, LevelReward,DailyQuest,StudentDailyQuest,Badge, StudentBadge, StudentProfile


class LessonInline(admin.TabularInline):
    model = Lesson
    extra = 0
    fields = ('subject', 'teacher', 'date', 'start_time', 'end_time', 'room', 'is_active')
    show_change_link = True


@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ('name',)
    search_fields = ('name',)


@admin.register(Lesson)
class LessonAdmin(admin.ModelAdmin):
    list_display = ('group', 'subject', 'teacher', 'date', 'start_time', 'end_time', 'room', 'is_active')
    list_filter = ('date', 'group', 'is_active')
    search_fields = ('group__name', 'subject', 'teacher', 'room')
    raw_id_fields = ('group',)


@admin.register(Group)
class GroupAdmin(admin.ModelAdmin):
    list_display = ('name', 'get_teachers')
    search_fields = ('name', 'teachers__user__username')
    filter_horizontal = ('teachers',)
    inlines = [LessonInline]
    ordering = ['name']

    def get_teachers(self, obj):
        return ", ".join([teacher.user.username for teacher in obj.teachers.all()])
    get_teachers.short_description = 'Teachers'


@admin.register(ShopItem)
class ShopItemAdmin(admin.ModelAdmin):
    list_display = ('name', 'price', 'item_type', 'is_active', 'validity_days')
    list_filter = ('item_type', 'is_active')
    search_fields = ('name', 'description')


@admin.register(Purchase)
class PurchaseAdmin(admin.ModelAdmin):
    list_display = ('code', 'student', 'item', 'status', 'created_at', 'expires_at')
    list_filter = ('status', 'created_at')
    search_fields = ('code', 'student__user__username', 'item__name')
    readonly_fields = ('code', 'created_at', 'activated_at')
    
    actions = ['mark_as_expired']

    @admin.action(description="Пометить выбранные как истёкшие")
    def mark_as_expired(self, request, queryset):
        queryset.filter(status='pending').update(status='expired')

@admin.register(TeacherInviteCode)
class TeacherInviteCodeAdmin(admin.ModelAdmin):
    list_display = ('code', 'is_active', 'max_uses', 'used_count', 'expires_at', 'created_at')
    list_filter = ('is_active', 'created_at')
    search_fields = ('code',)
    readonly_fields = ('created_at',)


@admin.register(GroupInviteCode)
class GroupInviteCodeAdmin(admin.ModelAdmin):
    list_display = ('code', 'group', 'teacher', 'is_active', 'max_uses', 'used_count', 'expires_at', 'created_at')
    list_filter = ('is_active', 'created_at', 'group')
    search_fields = ('code', 'group__name', 'teacher__user__username')
    readonly_fields = ('created_at',)


@admin.register(LevelReward)
class LevelRewardAdmin(admin.ModelAdmin):
    list_display = ('level', 'crystals_bonus', 'badge')

@admin.register(DailyQuest)
class DailyQuestAdmin(admin.ModelAdmin):
    list_display = ('quest_type', 'target_value', 'xp_reward', 'is_active')
    list_filter = ('quest_type', 'is_active')

@admin.register(StudentDailyQuest)
class StudentDailyQuestAdmin(admin.ModelAdmin):
    list_display = ('student', 'quest', 'progress', 'completed', 'date')
    list_filter = ('completed', 'date')
    search_fields = ('student__user__username', 'quest__quest_type')

@admin.register(Badge)
class BadgeAdmin(admin.ModelAdmin):
    list_display = ('name', 'condition_type', 'condition_value', 'xp_reward', 'crystal_reward')

@admin.register(StudentBadge)
class StudentBadgeAdmin(admin.ModelAdmin):
    list_display = ('student', 'badge', 'created_at')
    search_fields = ('student__user__username', 'badge__name')

@admin.register(StudentProfile)
class StudentProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'xp', 'level', 'crystals', 'group')
    search_fields = ('user__username', 'user__email')
