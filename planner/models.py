import uuid
from django.db import DEFAULT_DB_ALIAS, models, transaction


STATION_DATASET_CACHE_KEY = 'station-dataset-v1'


def invalidate_station_dataset(using):
    CacheEntry.objects.using(using).filter(pk=STATION_DATASET_CACHE_KEY).delete()


class StationQuerySet(models.QuerySet):
    def update(self, **kwargs):
        with transaction.atomic(using=self.db):
            result = super().update(**kwargs)
            invalidate_station_dataset(self.db)
            return result

    def delete(self):
        with transaction.atomic(using=self.db):
            result = super().delete()
            invalidate_station_dataset(self.db)
            return result

    def bulk_create(self, objs, *args, **kwargs):
        with transaction.atomic(using=self.db):
            result = super().bulk_create(objs, *args, **kwargs)
            invalidate_station_dataset(self.db)
            return result

    def bulk_update(self, objs, fields, *args, **kwargs):
        with transaction.atomic(using=self.db):
            result = super().bulk_update(objs, fields, *args, **kwargs)
            invalidate_station_dataset(self.db)
            return result


class Station(models.Model):
    objects = StationQuerySet.as_manager()

    source_id = models.CharField(max_length=80, db_index=True)
    name = models.CharField(max_length=255)
    address = models.CharField(max_length=255)
    city = models.CharField(max_length=255)
    state = models.CharField(max_length=2)
    rows = models.JSONField()
    price = models.FloatField()
    price_min = models.FloatField()
    price_max = models.FloatField()
    latitude = models.FloatField(null=True)
    longitude = models.FloatField(null=True)
    evidence = models.JSONField(default=dict)

    def save(self, *args, **kwargs):
        using = kwargs.get('using') or self._state.db or DEFAULT_DB_ALIAS
        with transaction.atomic(using=using):
            result = super().save(*args, **kwargs)
            invalidate_station_dataset(using)
            return result

    def delete(self, *args, **kwargs):
        using = kwargs.get('using') or (args[0] if args else None) or self._state.db or DEFAULT_DB_ALIAS
        with transaction.atomic(using=using):
            result = super().delete(*args, **kwargs)
            invalidate_station_dataset(using)
            return result


class City(models.Model):
    name = models.CharField(max_length=255, db_index=True)
    state = models.CharField(max_length=2)
    latitude = models.FloatField()
    longitude = models.FloatField()


class CacheEntry(models.Model):
    key = models.CharField(max_length=64, primary_key=True)
    value = models.JSONField()
    expires = models.DateTimeField()


class RoutePlan(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    result = models.JSONField()
    cache_key = models.CharField(max_length=64, db_index=True)
    created = models.DateTimeField(auto_now_add=True)
