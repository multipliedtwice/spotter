import uuid
from django.db import migrations, models

class Migration(migrations.Migration):
    initial = True
    dependencies = []
    operations = [
        migrations.CreateModel(name='Station', fields=[('id', models.BigAutoField(primary_key=True, serialize=False)), ('source_id', models.CharField(db_index=True, max_length=80)), ('name', models.CharField(max_length=255)), ('address', models.CharField(max_length=255)), ('city', models.CharField(max_length=255)), ('state', models.CharField(max_length=2)), ('rows', models.JSONField()), ('price', models.FloatField()), ('price_min', models.FloatField()), ('price_max', models.FloatField()), ('latitude', models.FloatField(null=True)), ('longitude', models.FloatField(null=True)), ('evidence', models.JSONField(default=dict))]),
        migrations.CreateModel(name='City', fields=[('id', models.BigAutoField(primary_key=True, serialize=False)), ('name', models.CharField(db_index=True, max_length=255)), ('state', models.CharField(max_length=2)), ('latitude', models.FloatField()), ('longitude', models.FloatField())]),
        migrations.CreateModel(name='CacheEntry', fields=[('key', models.CharField(max_length=64, primary_key=True, serialize=False)), ('value', models.JSONField()), ('expires', models.DateTimeField())]),
        migrations.CreateModel(name='RoutePlan', fields=[('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)), ('result', models.JSONField()), ('cache_key', models.CharField(db_index=True, max_length=64)), ('created', models.DateTimeField(auto_now_add=True))]),
    ]
