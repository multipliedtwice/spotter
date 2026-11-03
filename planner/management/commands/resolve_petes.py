from planner.management.commands.resolve_kwiktrip import Command as OperatorCommand
from planner.raw_operator_evidence import PETES_SOURCE, petes_source_brand, petes_source_numbers


class Command(OperatorCommand):
    help = "Resolve Pete's stations from published locator records."
    source_url = PETES_SOURCE
    namespaces = {'PETES': 'PETES'}
    datasource_name = "Pete's"
    unique_operator_points = True
    wrap_raw_records = True

    def source_brand(self, name):
        return petes_source_brand(name)

    def source_numbers(self, name):
        return petes_source_numbers(name)
