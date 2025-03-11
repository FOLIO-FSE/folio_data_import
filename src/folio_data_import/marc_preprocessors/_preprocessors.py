import pymarc
import logging

logger = logging.getLogger("folio_data_import.MARCDataImport")


def prepend_prefix_001(record: pymarc.Record, prefix: str) -> pymarc.Record:
    """
    Prepend a prefix to the record's 001 field.

    Args:
        record (pymarc.Record): The MARC record to preprocess.
        prefix (str): The prefix to prepend to the 001 field.

    Returns:
        pymarc.Record: The preprocessed MARC record.
    """
    record["001"].data = f"({prefix})" + record["001"].data
    return record


def prepend_ppn_prefix_001(record: pymarc.Record) -> pymarc.Record:
    """
    Prepend the PPN prefix to the record's 001 field. Useful when
    importing records from the ABES SUDOC catalog

    Args:
        record (pymarc.Record): The MARC record to preprocess.

    Returns:
        pymarc.Record: The preprocessed MARC record.
    """
    return prepend_prefix_001(record, "PPN")


def prepend_abes_prefix_001(record: pymarc.Record) -> pymarc.Record:
    """
    Prepend the ABES prefix to the record's 001 field. Useful when
    importing records from the ABES SUDOC catalog

    Args:
        record (pymarc.Record): The MARC record to preprocess.

    Returns:
        pymarc.Record: The preprocessed MARC record.
    """
    return prepend_prefix_001(record, "ABES")


def strip_999_ff_fields(record: pymarc.Record) -> pymarc.Record:
    """
    Strip all 999 fields with ff indicators from the record.
    Useful when importing records exported from another FOLIO system

    Args:
        record (pymarc.Record): The MARC record to preprocess.

    Returns:
        pymarc.Record: The preprocessed MARC record.
    """
    for field in record.get_fields("999"):
        if field.indicators == pymarc.Indicators(*["f", "f"]):
            record.remove_field(field)
    return record

def clean_999_fields(record: pymarc.Record) -> pymarc.Record:
    """
    The presence of 999 fields, with or without ff indicators, can cause
    issues with data import mapping in FOLIO. This function calls strip_999_ff_fields
    to remove 999 fields with ff indicators and then copies the remaining 999 fields
    to 945 fields.

    Args:
        record (pymarc.Record): The MARC record to preprocess.

    Returns:
        pymarc.Record: The preprocessed MARC record.
    """
    record = strip_999_ff_fields(record)
    for field in record.get_fields("999"):
        _945 = pymarc.Field(
            tag="945",
            indicators=field.indicators,
            subfields=field.subfields,
        )
        record.add_ordered_field(_945)
        record.remove_field(field)
    return record

def sudoc_supercede_prep(record: pymarc.Record) -> pymarc.Record:
    """
    Preprocesses a record from the ABES SUDOC catalog to copy 035 fields
    with a $9 subfield value of 'sudoc' to 935 fields with a $a subfield
    prefixed with "(ABES)". This is useful when importing newly-merged records
    from the SUDOC catalog when you want the new record to replace the old one
    in FOLIO. This also applyes the prepend_ppn_prefix_001 function to the record.

    Args:
        record (pymarc.Record): The MARC record to preprocess.

    Returns:
        pymarc.Record: The preprocessed MARC record.
    """
    record = prepend_abes_prefix_001(record)
    for field in record.get_fields("035"):
        if "a" in field and "9" in field and field["9"] == "sudoc":
            _935 = pymarc.Field(
                tag="935",
                indicators=["f", "f"],
                subfields=[pymarc.field.Subfield("a", "(ABES)" + field["a"])],
            )
            record.add_ordered_field(_935)
    return record


def clean_empty_fields(record: pymarc.Record) -> pymarc.Record:
    """
    Remove empty fields and subfields from the record. These can cause
    data import mapping issues in FOLIO. Removals are logged at custom
    log level 26, which is used by folio_migration_tools to populate the
    data issues report.

    Args:
        record (pymarc.Record): The MARC record to preprocess.

    Returns:
        pymarc.Record: The preprocessed MARC record.
    """
    MAPPED_FIELDS = {
        "010": ["a", "z"],
        "020": ["a", "y", "z"],
        "035": ["a", "z"],
        "040": ["a", "b", "c", "d", "e", "f", "g", "h", "k", "m", "n", "p", "r", "s"],
        "050": ["a", "b"],
        "082": ["a", "b"],
        "100": ["a", "b", "c", "d", "q"],
        "110": ["a", "b", "c"],
        "111": ["a", "c", "d"],
        "130": [
            "a",
            "d",
            "f",
            "k",
            "l",
            "m",
            "n",
            "o",
            "p",
            "r",
            "s",
            "t",
            "x",
            "y",
            "z",
        ],
        "180": ["x", "y", "z"],
        "210": ["a", "c"],
        "240": ["a", "f", "k", "l", "m", "n", "o", "p", "r", "s", "t", "x", "y", "z"],
        "245": ["a", "b", "c", "f", "g", "h", "k", "n", "p", "s"],
        "246": ["a", "f", "g", "n", "p", "s"],
        "250": ["a", "b"],
        "260": ["a", "b", "c", "e", "f", "g"],
        "300": ["a", "b", "c", "e", "f", "g"],
        "440": ["a", "n", "p", "v", "x", "y", "z"],
        "490": ["a", "v", "x", "y", "z"],
        "500": ["a", "c", "d", "n", "p", "v", "x", "y", "z"],
        "505": ["a", "g", "r", "t", "u"],
        "520": ["a", "b", "c", "u"],
        "600": ["a", "b", "c", "d", "q", "t", "v", "x", "y", "z"],
        "610": ["a", "b", "c", "d", "t", "v", "x", "y", "z"],
        "611": ["a", "c", "d", "t", "v", "x", "y", "z"],
        "630": [
            "a",
            "d",
            "f",
            "k",
            "l",
            "m",
            "n",
            "o",
            "p",
            "r",
            "s",
            "t",
            "x",
            "y",
            "z",
        ],
        "650": ["a", "d", "v", "x", "y", "z"],
        "651": ["a", "v", "x", "y", "z"],
        "655": ["a", "v", "x", "y", "z"],
        "700": ["a", "b", "c", "d", "q", "t", "v", "x", "y", "z"],
        "710": ["a", "b", "c", "d", "t", "v", "x", "y", "z"],
        "711": ["a", "c", "d", "t", "v", "x", "y", "z"],
        "730": [
            "a",
            "d",
            "f",
            "k",
            "l",
            "m",
            "n",
            "o",
            "p",
            "r",
            "s",
            "t",
            "x",
            "y",
            "z",
        ],
        "740": ["a", "n", "p", "v", "x", "y", "z"],
        "800": ["a", "b", "c", "d", "q", "t", "v", "x", "y", "z"],
        "810": ["a", "b", "c", "d", "t", "v", "x", "y", "z"],
        "811": ["a", "c", "d", "t", "v", "x", "y", "z"],
        "830": [
            "a",
            "d",
            "f",
            "k",
            "l",
            "m",
            "n",
            "o",
            "p",
            "r",
            "s",
            "t",
            "x",
            "y",
            "z",
        ],
        "856": ["u", "y", "z"],
    }

    for field in list(record.get_fields()):
        len_subs = len(field.subfields)
        subfield_value = bool(field.subfields[0].value) if len_subs > 0 else False
        if not int(field.tag) >= 900 and field.tag in MAPPED_FIELDS:
            if int(field.tag) > 9 and len_subs == 0:
                logger.log(
                    26,
                    "DATA ISSUE\t%s\t%s\t%s",
                    record["001"].value(),
                    f"{field.tag} is empty, removing field",
                    field,
                )
                record.remove_field(field)
            elif len_subs == 1 and not subfield_value:
                logger.log(
                    26,
                    "DATA ISSUE\t%s\t%s\t%s",
                    record["001"].value(),
                    f"{field.tag}${field.subfields[0].code} is empty, no other subfields present, removing field",
                    field,
                )
                record.remove_field(field)
            else:
                if len_subs > 1 and "a" in field and not field["a"].strip():
                    logger.log(
                        26,
                        "DATA ISSUE\t%s\t%s\t%s",
                        record["001"].value(),
                        f"{field.tag}$a is empty, removing subfield",
                        field,
                    )
                    field.delete_subfield("a")
                for idx, subfield in enumerate(list(field.subfields), start=1):
                    if (
                        subfield.code in MAPPED_FIELDS.get(field.tag, [])
                        and not subfield.value
                    ):
                        logger.log(
                            26,
                            "DATA ISSUE\t%s\t%s\t%s",
                            record["001"].value(),
                            f"{field.tag}${subfield.code} ({ordinal(idx)} subfield) is empty, but other subfields have values, removing subfield",
                            field,
                        )
                        field.delete_subfield(subfield.code)
                if len(field.subfields) == 0:
                    logger.log(
                        26,
                        "DATA ISSUE\t%s\t%s\t%s",
                        record["001"].value(),
                        f"{field.tag} has no non-empty subfields after cleaning, removing field",
                        field,
                    )
                    record.remove_field(field)
    return record


def fix_leader(record: pymarc.Record) -> pymarc.Record:
    """
    Fixes the leader of the record by setting the record status to 'c' (modified
    record) and the type of record to 'a' (language material).

    Args:
        record (pymarc.Record): The MARC record to preprocess.

    Returns:
        pymarc.Record: The preprocessed MARC record.
    """
    VALID_STATUSES = ["a", "c", "d", "n", "p"]
    VALID_TYPES = ["a", "c", "d", "e", "f", "g", "i", "j", "k", "m", "o", "p", "r", "t"]
    if record.leader[5] not in VALID_STATUSES:
        logger.log(
            26,
            "DATA ISSUE\t%s\t%s\t%s",
            record["001"].value(),
            f"Invalid record status: {record.leader[5]}, setting to 'c'",
            record,
        )
        record.leader = pymarc.Leader(record.leader[:5] + "c" + record.leader[6:])
    if record.leader[6] not in VALID_TYPES:
        logger.log(
            26,
            "DATA ISSUE\t%s\t%s\t%s",
            record["001"].value(),
            f"Invalid record type: {record.leader[6]}, setting to 'a'",
            record,
        )
        record.leader = pymarc.Leader(record.leader[:6] + "a" + record.leader[7:])
    return record


def ordinal(n):
    s = ("th", "st", "nd", "rd") + ("th",) * 10
    v = n % 100
    if v > 13:
        return f"{n}{s[v % 10]}"
    else:
        return f"{n}{s[v]}"
