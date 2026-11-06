"""
        Allowed values of the "declaration type" field, used
        when checking the submitted values. The values are the official customs
        codes, written in Cyrillic in the source files (EK.. = export, IM.. = import,
        TR.. = transit), so they are kept as they are:
            Export - export_full;
            Export (periodic) - export_periodic;
            Re-export - re_export;
            Temporary import of goods - import_temporary_storage;
            Temporary export of goods - export_temporary_storage;
            Import - import_full;
            Import (temporary) - import_partial;
            Import (periodic) - import_periodic;
            Re-import - re_import;
            Processing within the customs territory - processing_internal;
            Processing outside the customs territory - processing_external;
            Duty-free trade - import_duty_free, export_duty_free;
            Abandonment of goods in favour of the state - states_favour;
            Transit of goods - transit;
            End of the regime (return of goods) - import_released, export_released.
"""

from enum import Enum

from application.configuration_handling import settings
from models.logic.pydantic_helper import auto_enum


class _DefaultDeclarationTypesEnum(str, Enum):
    export_full = "ЭК10"
    export_periodic = "ЭК10П"
    re_export = "ЭК11"
    import_temporary_admitted = "ИМ31"
    export_temporary_admitted = "ЭК32"
    import_full = "ИМ40"
    import_temporary = "ИМ40В"
    import_periodic = "ИМ40П"
    re_import = "ИМ41"
    processing_internal = "ИМ51"
    processing_external = "ЭК61"
    import_duty_free = "ИМ72"
    export_duty_free = "ЭК72"
    states_favour = "ИМ75"
    transit = "ТР80"
    import_released = "ИМ00"
    export_released = "ЭК00"


if settings.get("declaration_types_allow_list"):
    # Generated from config: member names are the configured values.
    DeclarationTypesEnum = auto_enum("DeclarationTypesEnum", settings.declaration_types_allow_list)
else:
    DeclarationTypesEnum = _DefaultDeclarationTypesEnum
