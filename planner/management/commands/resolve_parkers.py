import json
from pathlib import Path

from django.core.management.base import CommandError

from planner.management.commands.resolve_kwiktrip import Command as OperatorCommand
from planner.raw_operator_evidence import PARKERS_SOURCE, parkers_source_brand, parkers_source_numbers, validated_parkers_records


class Command(OperatorCommand):
    help = "Resolve Parker's stations from published locator records."
    source_url = PARKERS_SOURCE
    namespaces = {'PARKERS': 'PARKERS'}
    datasource_name = "Parker's"
    unique_operator_points = True
    wrap_raw_records = True

    def source_brand(self, name):
        return parkers_source_brand(name)

    def source_numbers(self, name):
        return parkers_source_numbers(name)

    def handle(self, input, **options):
        try:
            validated_parkers_records(json.loads(Path(input).read_text(encoding='utf-8')))
        except (OSError, UnicodeError, ValueError, TypeError, KeyError) as exc:
            raise CommandError('Valid Parker catalog required.') from exc
        return super().handle(input=input, **options)
