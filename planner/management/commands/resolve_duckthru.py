from planner.management.commands.resolve_kwiktrip import Command as OperatorCommand
from planner.raw_operator_evidence import DUCKTHRU_SOURCE, duckthru_source_brand


class Command(OperatorCommand):
    help = "Resolve Duck Thru stations from published locator records."
    source_url = DUCKTHRU_SOURCE
    namespaces = {'DUCK THRU': 'DUCK THRU'}
    datasource_name = 'Duck Thru'
    unique_operator_points = True
    wrap_raw_records = True

    def source_brand(self, name):
        return duckthru_source_brand(name)
