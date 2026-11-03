from planner.management.commands.resolve_kwiktrip import Command as OperatorCommand
from planner.raw_operator_evidence import SPINX_SOURCE, spinx_source_brand, spinx_source_numbers


class Command(OperatorCommand):
    help = "Resolve Spinx stations from published locator records."
    source_url = SPINX_SOURCE
    namespaces = {'SPINX': 'SPINX'}
    datasource_name = 'Spinx'
    unique_operator_points = True
    wrap_raw_records = True

    def source_brand(self, name):
        return spinx_source_brand(name)

    def source_numbers(self, name):
        return spinx_source_numbers(name)
