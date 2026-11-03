from planner.management.commands.resolve_kwiktrip import Command as OperatorCommand
from planner.raw_operator_evidence import KENTKWIK_SOURCE, kentkwik_source_brand, kentkwik_source_numbers, validated_kentkwik_records


class Command(OperatorCommand):
    help = "Resolve Kent Kwik stations from published locator records."
    source_url = KENTKWIK_SOURCE
    namespaces = {'KENT KWIK': 'KENT KWIK'}
    datasource_name = "Kent Kwik"
    unique_operator_points = True
    wrap_raw_records = True

    def source_brand(self, name):
        return kentkwik_source_brand(name)

    def source_numbers(self, name):
        return kentkwik_source_numbers(name)

    def catalog_stores(self, asset):
        return validated_kentkwik_records(asset)
