from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from api.models import Notification
from api.serializers import NotificationSerializer

class NotificationListView(generics.ListAPIView):
    """Список уведомлений текущего пользователя."""
    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Notification.objects.filter(recipient=self.request.user)

class NotificationUnreadCountView(APIView):
    """Количество непрочитанных уведомлений."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        count = Notification.objects.filter(recipient=request.user, is_read=False).count()
        return Response({'unread_count': count})

class NotificationMarkReadView(APIView):
    """Отметить уведомления прочитанными (по ID или все)."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        ids = request.data.get('ids', [])
        if ids:
            Notification.objects.filter(recipient=request.user, id__in=ids).update(is_read=True)
        else:
            Notification.objects.filter(recipient=request.user, is_read=False).update(is_read=True)
        return Response({'status': 'ok'})
