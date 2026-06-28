from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0003_assignment_status_due_date'),
    ]

    operations = [
        migrations.AlterField(
            model_name='assignment',
            name='status',
            field=models.CharField(
                choices=[('issued', 'Issued'), ('submitted', 'Submitted'), ('under_review', 'Under Review'), ('graded', 'Graded'), ('revoked', 'Revoked')], 
                default='issued', 
                max_length=32,
            ),
        ),
    ]