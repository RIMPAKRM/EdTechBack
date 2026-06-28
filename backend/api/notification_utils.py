from django.contrib.auth.models import User
from api.models import Notification

def create_notification(recipient, notification_type, title, message, sender=None, link=''):
    """Удобная функция для создания уведомления."""
    Notification.objects.create(
        recipient=recipient,
        sender=sender,
        notification_type=notification_type,
        title=title,
        message=message,
        link=link
    )
