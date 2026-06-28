from rest_framework import serializers
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework_simplejwt.tokens import RefreshToken
from django.db import transaction
from api.models import TeacherProfile, StudentProfile, TeacherInviteCode, ShopItem, Purchase, Group, Assignment, Subject, Lesson, Attendance, StudentStatistics, Notification

User = get_user_model()


class AssignmentSerializer(serializers.ModelSerializer):
    effective_status = serializers.SerializerMethodField(read_only=True)
    teacher = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = Assignment
        fields = "__all__"

    def get_effective_status(self, obj):
        return obj.effective_status


class GroupSerializer(serializers.ModelSerializer):
    teachers = serializers.PrimaryKeyRelatedField(many=True, read_only=True)

    class Meta:
        model = Group
        fields = "__all__"


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, validators=[validate_password])
    password2 = serializers.CharField(write_only=True)
    role = serializers.ChoiceField(choices=["student", "teacher"], write_only=True)
    teacher_code = serializers.CharField(required=False, allow_blank=True)
    group_code = serializers.CharField(required=False, allow_blank=True)

    class Meta:
        model = User
        fields = (
            "username",
            "first_name",
            "last_name",
            "email",
            "password",
            "password2",
            "role",
            "teacher_code",
            "group_code",
        )

    def validate(self, attrs):
        if attrs["password"] != attrs["password2"]:
            raise serializers.ValidationError("Пароли не совпадают")

        if attrs["role"] == "teacher":
            code = attrs.get("teacher_code")
            if not code:
                raise serializers.ValidationError("Требуется код преподавателя")

            invite = TeacherInviteCode.objects.filter(code=code, is_active=True).first()
            if not invite or not invite.is_valid():
                raise serializers.ValidationError("Некорректный код преподавателя")

        if attrs["role"] == "student":
            group_code = attrs.get("group_code")
            if not group_code:
                raise serializers.ValidationError("Требуется код группы")

            from api.models import GroupInviteCode
            invite = GroupInviteCode.objects.filter(code=group_code).first()
            if not invite or not invite.is_valid():
                raise serializers.ValidationError("Некорректный код группы")

        return attrs

    def create(self, validated_data):
        validated_data.pop("password2")
        role = validated_data.pop("role")
        teacher_code = validated_data.pop("teacher_code", None)
        group_code = validated_data.pop("group_code", None)

        with transaction.atomic():
            user = User.objects.create_user(**validated_data)

            if role == "student":
                student_profile = StudentProfile.objects.create(user=user)

                if group_code:
                    from api.models import GroupInviteCode
                    invite = GroupInviteCode.objects.filter(code=group_code).first()
                    if invite and invite.is_valid():
                        invite.use(student_profile)

            elif role == "teacher":
                TeacherProfile.objects.create(user=user)
                if teacher_code:
                    TeacherInviteCode.objects.filter(code=teacher_code).update(
                        is_active=False
                    )

        return user


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField()

    def validate(self, attrs):
        user = User.objects.filter(email__iexact=attrs["email"]).first()

        if not user or not user.check_password(attrs["password"]):
            raise serializers.ValidationError("Неверные учётные данные")

        refresh = RefreshToken.for_user(user)
        role = None
        if hasattr(user, 'studentprofile'):
            role = 'student'
        elif hasattr(user, 'teacherprofile'):
            role = 'teacher'

        return {
            "refresh": str(refresh),
            "access": str(refresh.access_token),
            "role": role,
        }


class StudentProfileSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source="user.username", read_only=True)
    avatar = serializers.ImageField(write_only=True, required=False, allow_null=True)
    avatar_url = serializers.SerializerMethodField(read_only=True)
    first_name = serializers.CharField(source="user.first_name", read_only=True)
    last_name = serializers.CharField(source="user.last_name", read_only=True)
    email = serializers.CharField(source="user.email", read_only=True)

    class Meta:
        model = StudentProfile
        fields = (
            "username",
            "first_name",
            "last_name",
            "email",
            "xp",
            "level",
            "group",
            "crystals",
            "avatar",
            "avatar_url",
        )

    def get_avatar_url(self, obj):
        if not obj.avatar:
            return None

        request = self.context.get("request")
        url = obj.avatar.url
        return request.build_absolute_uri(url) if request else url


class TeacherProfileSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source="user.username", read_only=True)
    avatar = serializers.ImageField(write_only=True, required=False, allow_null=True)
    avatar_url = serializers.SerializerMethodField(read_only=True)
    first_name = serializers.CharField(source="user.first_name", read_only=True)
    last_name = serializers.CharField(source="user.last_name", read_only=True)
    email = serializers.CharField(source="user.email", read_only=True)

    class Meta:
        model = TeacherProfile
        fields = ("username", "first_name", "last_name", "email", "avatar", "avatar_url")

    def get_avatar_url(self, obj):
        if not obj.avatar:
            return None

        request = self.context.get("request")
        url = obj.avatar.url
        return request.build_absolute_uri(url) if request else url


class LessonSerializer(serializers.ModelSerializer):
    group = serializers.PrimaryKeyRelatedField(queryset=Group.objects.all())

    class Meta:
        model = Lesson
        fields = "__all__"


class LessonCreateSerializer(serializers.ModelSerializer):
    group = serializers.PrimaryKeyRelatedField(queryset=Group.objects.all(), required=False, allow_null=True)

    class Meta:
        model = Lesson
        fields = ("id", "group", "subject", "teacher", "date", "start_time", "end_time", "room", "is_active")
        read_only_fields = ("id",)


class ShopItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = ShopItem
        fields = ('id', 'name', 'description', 'price', 'item_type', 'image_url', 'validity_days')

class PurchaseSerializer(serializers.ModelSerializer):
    item = ShopItemSerializer(read_only=True)
    
    class Meta:
        model = Purchase
        fields = ('id', 'item', 'status', 'code', 'created_at', 'activated_at', 'expires_at')

class StudentStatisticsSerializer(serializers.ModelSerializer):
    student_username = serializers.CharField(source='student.user.username', read_only=True)
    student_first_name = serializers.CharField(source='student.user.first_name', read_only=True)
    student_last_name = serializers.CharField(source='student.user.last_name', read_only=True)
    group_name = serializers.CharField(source='student.group.name', read_only=True)
    
    class Meta:
        model = StudentStatistics
        fields = [
            'id', 'student', 'student_username', 'student_first_name', 'student_last_name',
            'group_name', 'rank', 'completed_assignments', 'incomplete_assignments',
            'total_xp', 'updated_at'
        ]
        read_only_fields = ['id', 'updated_at']
        
__all__ = [
    "AssignmentSerializer",
    "GroupSerializer",
    "RegisterSerializer",
    "LoginSerializer",
    "StudentProfileSerializer",
    "TeacherProfileSerializer",
    "LessonSerializer",
    "StudentStatisticsSerializer",
]


class AttendanceSerializer(serializers.ModelSerializer):
    student_id = serializers.IntegerField(source='student.id', read_only=True)
    student_name = serializers.SerializerMethodField()

    class Meta:
        model = Attendance
        fields = ['id', 'student_id', 'student_name', 'is_present', 'crystals_granted', 'grade', 'crystals_awarded']
        read_only_fields = ['id', 'crystals_granted']

    def get_student_name(self, obj):
        return f"{obj.student.user.first_name} {obj.student.user.last_name}"


class NotificationSerializer(serializers.ModelSerializer):
    sender_name = serializers.CharField(source='sender.username', read_only=True)

    class Meta:
        model = Notification
        fields = ['id', 'recipient', 'sender', 'sender_name', 'notification_type',
                  'title', 'message', 'link', 'is_read', 'created_at']
        read_only_fields = ['id', 'created_at']
