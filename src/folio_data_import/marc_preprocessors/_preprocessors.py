import pymarc

def prepend_prefix_001(record: pymarc.Record, prefix: str) -> pymarc.Record:
    """
    Prepend a prefix to the record's 001 field.

    Args:
        record (pymarc.Record): The MARC record to preprocess.
        prefix (str): The prefix to prepend to the 001 field.

    Returns:
        pymarc.Record: The preprocessed MARC record.
    """
    record['001'].data = f'({prefix})' + record['001'].data
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
    return prepend_prefix_001(record, 'PPN')

def prepend_abes_prefix_001(record: pymarc.Record) -> pymarc.Record:
    """
    Prepend the ABES prefix to the record's 001 field. Useful when
    importing records from the ABES SUDOC catalog

    Args:
        record (pymarc.Record): The MARC record to preprocess.

    Returns:
        pymarc.Record: The preprocessed MARC record.
    """
    return prepend_prefix_001(record, 'ABES')

def strip_999_ff_fields(record: pymarc.Record) -> pymarc.Record:
    """
    Strip all 999 fields with ff indicators from the record.
    Useful when importing records exported from another FOLIO system

    Args:
        record (pymarc.Record): The MARC record to preprocess.

    Returns:
        pymarc.Record: The preprocessed MARC record.
    """
    for field in record.get_fields('999'):
        if field.indicators == pymarc.Indicators(*['f', 'f']):
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
    for field in record.get_fields('035'):
        if "a" in field and "9" in field and field['9'] == 'sudoc':
            _935 = pymarc.Field(
                tag='935',
                indicators=['f', 'f'],
                subfields=[
                    pymarc.field.Subfield('a', "(ABES)" + field['a'])
                ]
            )
            record.add_ordered_field(_935)
    return record