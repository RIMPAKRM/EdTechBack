from django.http import JsonResponse
import traceback
import sys

class JsonDebugErrorMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        exc_type, exc_value, exc_traceback = sys.exc_info()
        error_message = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
        
        return JsonResponse({
            "error": str(exception),
            "type": exc_type.__name__,
            "traceback": error_message
        }, status=500)
