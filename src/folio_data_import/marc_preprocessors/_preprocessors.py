import importlib
import logging
import re
import sys
from typing import Callable, Dict, List, Tuple, Union

import pymarc
from pymarc.record import Record

logger = logging.getLogger("folio_data_import.MARCDataImport")


class MARCPreprocessor:
    """
    A class to preprocess MARC records for data import into FOLIO.
    """

    def __init__(self, preprocessors: Union[str, List[Callable]], **kwargs) -> None:
        """
        Initialize the MARCPreprocessor with a list of preprocessors.

        Args:
            preprocessors (Union[str, List[Callable]]): A string of comma-separated function names
                or a list of callable preprocessor functions to apply.
        """
        self.preprocessor_args: Dict[str, Dict] = kwargs
        self.preprocessors: List[Tuple[Callable, Dict]] = self._get_preprocessor_functions(
            preprocessors
        )
        self.proc_kwargs = kwargs
        self.record = None

    def _get_preprocessor_args(self, func: Callable) -> Dict:
        """
        Get the arguments for the preprocessor function.

        Args:
            func (Callable): The preprocessor function.

        Returns:
            Dict: A dictionary of arguments for the preprocessor function.
        """
        func_path = f"{func.__module__}.{func.__name__}"
        path_args: Dict = self.preprocessor_args.get("default", {})
        path_args.update(self.preprocessor_args.get(func.__name__, {}))
        path_args.update(self.preprocessor_args.get(func_path, {}))
        return path_args

    def _get_preprocessor_functions(
        self, func_list: str | List[Callable]
    ) -> List[Tuple[Callable, Dict]]:
        """
        Get the preprocessor functions based on the provided names.

        Args:
            func_list (Union[str, List[Callable]]): A string of comma-separated function names or a
                list of callable preprocessor functions.

        Returns:
            List[callable]: A list of preprocessor functions.
        """
        preprocessors: List[Tuple[Callable, Dict]] = []
        if isinstance(func_list, str):
            func_paths = [f.strip() for f in func_list.split(",")]
        else:
            for f in func_list:
                if not callable(f):
                    logger.warning(f"Preprocessing function {f} is not callable. Skipping.")
                else:
                    preprocessors.append((f, self._get_preprocessor_args(f)))
            return preprocessors
        for f_path in func_paths:
            f_import = f_path.rsplit(".", 1)
            if len(f_import) == 1:
                # If the function is not a full path, assume it's in the current module
                if func := getattr(sys.modules[__name__], f_import[0], None):
                    if callable(func):
                        preprocessors.append((func, self._get_preprocessor_args(func)))
                    else:
                        logger.warning(
                            f"Preprocessing function {f_path} is not callable. Skipping."
                        )
                else:
                    logger.warning(
                        f"Preprocessing function {f_path} not found in current module. Skipping."
                    )
            elif len(f_import) == 2:
                # If the function is a full path, import it
                module_path, func_name = f_import
                try:
                    module = importlib.import_module(module_path)
                    func = getattr(module, func_name)
                    preprocessors.append((func, self._get_preprocessor_args(func)))
                except ImportError as e:
                    logger.warning(
                        f"Error importing preprocessing function {f_path}: {e}. Skipping."
                    )
        return preprocessors

    def do_work(self, record: Record) -> Record:
        """
        Preprocess the MARC record.
        """
        for proc, kwargs in self.preprocessors:
            record = proc(record, **kwargs)
        return record


def prepend_prefix_001(record: Record, prefix: str) -> Record:
    """
    Prepend a prefix to the record's 001 field.

    Args:
        record (Record): The MARC record to preprocess.
        prefix (str): The prefix to prepend to the 001 field.

    Returns:
        Record: The preprocessed MARC record.
    """
    if "001" in record:
        record["001"].data = (
            f"({prefix})" + record["001"].data if record["001"].data else f"({prefix})"
        )
    else:
        logger.warning("Field '001' not found in record. Skipping prefix prepend.")
    return record


def prepend_ppn_prefix_001(record: Record, **kwargs) -> Record:
    """
    Prepend the PPN prefix to the record's 001 field. Useful when
    importing records from the ABES SUDOC catalog

    Args:
        record (Record): The MARC record to preprocess.

    Returns:
        Record: The preprocessed MARC record.
    """
    return prepend_prefix_001(record, "PPN")


def prepend_abes_prefix_001(record: Record, **kwargs) -> Record:
    """
    Prepend the ABES prefix to the record's 001 field. Useful when
    importing records from the ABES SUDOC catalog

    Args:
        record (Record): The MARC record to preprocess.

    Returns:
        Record: The preprocessed MARC record.
    """
    return prepend_prefix_001(record, "ABES")


def strip_999_ff_fields(record: Record, **kwargs) -> Record:
    """
    Strip all 999 fields with ff indicators from the record.
    Useful when importing records exported from another FOLIO system

    Args:
        record (Record): The MARC record to preprocess.

    Returns:
        Record: The preprocessed MARC record.
    """
    for field in record.get_fields("999"):
        if field.indicators == pymarc.Indicators(*["f", "f"]):
            record.remove_field(field)
    return record


def clean_999_fields(record: Record, **kwargs) -> Record:
    """
    The presence of 999 fields, with or without ff indicators, can cause
    issues with data import mapping in FOLIO. This function calls strip_999_ff_fields
    to remove 999 fields with ff indicators and then copies the remaining 999 fields
    to 945 fields.

    Args:
        record (Record): The MARC record to preprocess.

    Returns:
        Record: The preprocessed MARC record.
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


def clean_non_ff_999_fields(record: Record, **kwargs) -> Record:
    """
    When loading migrated MARC records from folio_migration_tools, the presence of other 999 fields
    than those set by the migration process can cause the record to fail to load properly. This
    preprocessor function moves all 999 fields with non-ff indicators to 945 fields with 99
    indicators.
    """
    for field in record.get_fields("999"):
        if field.indicators != pymarc.Indicators(*["f", "f"]):
            logger.log(
                26,
                "DATA ISSUE\t%s\t%s\t%s",
                record["001"].value(),
                "Record contains a 999 field with non-ff indicators: Moving field to a 945 with"
                ' indicators "99"',
                field,
            )
            _945 = pymarc.Field(
                tag="945",
                indicators=pymarc.Indicators("9", "9"),
                subfields=field.subfields,
            )
            record.add_ordered_field(_945)
            record.remove_field(field)
    return record


def sudoc_supercede_prep(record: Record, **kwargs) -> Record:
    """
    Preprocesses a record from the ABES SUDOC catalog to copy 035 fields
    with a $9 subfield value of 'sudoc' to 935 fields with a $a subfield
    prefixed with "(ABES)". This is useful when importing newly-merged records
    from the SUDOC catalog when you want the new record to replace the old one
    in FOLIO. This also applyes the prepend_ppn_prefix_001 function to the record.

    Args:
        record (Record): The MARC record to preprocess.

    Returns:
        Record: The preprocessed MARC record.
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


def clean_empty_fields(record: Record, **kwargs) -> Record:
    """
    Remove empty fields and subfields from the record. These can cause
    data import mapping issues in FOLIO. Removals are logged at custom
    log level 26, which is used by folio_migration_tools to populate the
    data issues report.

    Args:
        record (Record): The MARC record to preprocess.

    Returns:
        Record: The preprocessed MARC record.
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

    for field in record.get_fields(*MAPPED_FIELDS.keys()):
        len_subs = len(field.subfields)
        subfield_value = (
            bool(re.sub(r"[.,-]", "", field.subfields[0].value).strip()) if len_subs else False
        )
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
                f"{field.tag}${field.subfields[0].code} is empty,"
                " no other subfields present, removing field",
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
                if subfield.code in MAPPED_FIELDS.get(field.tag, []) and not subfield.value:
                    logger.log(
                        26,
                        "DATA ISSUE\t%s\t%s\t%s",
                        record["001"].value(),
                        f"{field.tag}${subfield.code} ({ordinal(idx)} subfield) is empty, but "
                        "other subfields have values, removing subfield",
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


def fix_bib_leader(record: Record, **kwargs) -> Record:
    """
    Fixes the leader of the record by setting the record status to 'c' (modified
    record) and the type of record to 'a' (language material).

    Args:
        record (Record): The MARC record to preprocess.

    Returns:
        Record: The preprocessed MARC record.
    """
    VALID_STATUSES = ["a", "c", "d", "n", "p"]
    VALID_TYPES = ["a", "c", "d", "e", "f", "g", "i", "j", "k", "m", "o", "p", "r", "t"]
    if record.leader[5] not in VALID_STATUSES:
        logger.log(
            26,
            "DATA ISSUE\t%s\t%s\t%s",
            record["001"].value(),
            f"Invalid record status: {record.leader[5]}, setting to 'c'",
            record.leader,
        )
        record.leader = pymarc.Leader(record.leader[:5] + "c" + record.leader[6:])
    if record.leader[6] not in VALID_TYPES:
        logger.log(
            26,
            "DATA ISSUE\t%s\t%s\t%s",
            record["001"].value(),
            f"Invalid record type: {record.leader[6]}, setting to 'a'",
            record.leader,
        )
        record.leader = pymarc.Leader(record.leader[:6] + "a" + record.leader[7:])
    return record


def move_authority_subfield_9_to_0_all_controllable_fields(record: Record, **kwargs) -> Record:
    """
    Move subfield 9 from authority fields to subfield 0. This is useful when
    importing records from the ABES SUDOC catalog.

    Args:
        record (Record): The MARC record to preprocess.

    Returns:
        Record: The preprocessed MARC record.
    """
    controlled_fields = [
        "100",
        "110",
        "111",
        "130",
        "600",
        "610",
        "611",
        "630",
        "650",
        "651",
        "655",
        "700",
        "710",
        "711",
        "730",
        "800",
        "810",
        "811",
        "830",
        "880",
    ]
    for field in record.get_fields(*controlled_fields):
        _subfields = field.get_subfields("9")
        for subfield in _subfields:
            field.add_subfield("0", subfield)
            field.delete_subfield("9")
            logger.log(
                26,
                "DATA ISSUE\t%s\t%s\t%s",
                record["001"].value(),
                f"Subfield 9 moved to subfield 0 in {field.tag}",
                field,
            )
    return record


def ordinal(n: int) -> str:
    s = ("th", "st", "nd", "rd") + ("th",) * 10
    v = n % 100
    if v > 13:
        return f"{n}{s[v % 10]}"
    else:
        return f"{n}{s[v]}"
