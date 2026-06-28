from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0002_alter_studentprofile_crystals_assignment'),
    ]

    operations = [
        migrations.AddField(
            model_name='assignment',
            name='status',
            field=models.CharField(choices=[('issued', 'Issued'), ('submitted', 'Submitted'), ('under_review', 'Under Review'), ('graded', 'Graded'), ('revoked', 'Revoked')], default='issued', max_length=32),
        ),
        migrations.AddField(
            model_name='assignment',
            name='due_date',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='assignment',
            name='is_retracted',
            field=models.BooleanField(default=False),
        ),
    ]
