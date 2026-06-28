from django.db import migrations

def add_default_daily_quest(apps, schema_editor):
    DailyQuest = apps.get_model('api', 'DailyQuest')
    
    if not DailyQuest.objects.filter(quest_type='submit_assignment', target_value=1).exists():
        DailyQuest.objects.create(
            quest_type='submit_assignment',
            target_value=1,
            xp_reward=20,
            crystal_reward=1,
            is_active=True
        )

class Migration(migrations.Migration):
    dependencies = [
        ('api', '0024_merge_20260622_1847'),
    ]

    operations = [
        migrations.RunPython(add_default_daily_quest),
    ]
