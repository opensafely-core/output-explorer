from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = """
        Create an admin/admin superuser if it doesn't already exist. For development use only.
    """  # noqa: A003

    def handle(self, *args, **options):
        User = get_user_model()

        if not User.objects.filter(username="admin").exists():
            User.objects.create_superuser("admin", "admin@example.com", "admin")
