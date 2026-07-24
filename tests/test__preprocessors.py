import pytest
import pymarc
from folio_data_import.marc_preprocessors._preprocessors import (
    _get_record_id,
    MARCPreprocessor,
    clean_non_ff_999_fields,
    fix_bib_leader,
    normalize_subfield_codes,
    copy_240_to_245_if_no_245,
    prepend_prefix_001,
    prepend_ppn_prefix_001,
    prepend_abes_prefix_001,
    strip_999_ff_fields,
    sudoc_supercede_prep,
    clean_empty_fields,
    clean_999_fields,
)


def test_prepend_ppn_prefix_001():
    processor = MARCPreprocessor("prepend_ppn_prefix_001")
    record = pymarc.Record()
    record.add_field(pymarc.Field(tag='001', data='123456'))
    record = processor.do_work(record)
    assert record['001'].data == '(PPN)123456'


def test_prepend_abes_prefix_001():
    processor = MARCPreprocessor("prepend_abes_prefix_001")
    record = pymarc.Record()
    record.add_field(pymarc.Field(tag='001', data='123456'))
    record = processor.do_work(record)
    assert record['001'].data == '(ABES)123456'


def test_prepend_prefix_001():
    record = pymarc.Record()
    record.add_field(pymarc.Field(tag='001', data='123456'))
    record = prepend_prefix_001(record, 'TEST')
    assert record['001'].data == '(TEST)123456'


def test_strip_999_ff_fields():
    processor = MARCPreprocessor("strip_999_ff_fields")
    record = pymarc.Record()
    record.add_field(pymarc.Field(tag='999', indicators=['f', 'f']))
    record.add_field(pymarc.Field(tag='999', indicators=[' ', ' ']))
    record = processor.do_work(record)
    assert len(record.get_fields('999')) == 1


def test_sudoc_supercede_prep():
    processor = MARCPreprocessor("sudoc_supercede_prep")
    record = pymarc.Record()
    record.add_field(pymarc.Field(tag='001', data='123456'))
    record.add_field(pymarc.Field(tag='035', indicators=['', ''], subfields=[
        pymarc.field.Subfield('a', '234567'),
        pymarc.field.Subfield('9', 'sudoc')
    ]))
    record.add_field(pymarc.Field(tag='035', indicators=['', ''], subfields=[
        pymarc.field.Subfield('a', '345678'),
        pymarc.field.Subfield('9', 'sudoc')
    ]))
    record = processor.do_work(record)
    assert record.get_fields('935')[0]["a"] == '(ABES)234567'
    assert record.get_fields('935')[1]["a"] == '(ABES)345678'
    assert record['001'].data == '(ABES)123456'


def test_clean_empty_fields():
    processor = MARCPreprocessor("clean_empty_fields")
    record = pymarc.Record()
    record.add_field(pymarc.Field(tag='001', data='123456'))
    bad_010 = pymarc.Field(tag='010', indicators=[' ', ' '], subfields=[
        pymarc.field.Subfield('a', '')
    ])
    record.add_field(bad_010)
    bad_020 = pymarc.Field(tag='020', indicators=[' ', ' '], subfields=[
        pymarc.field.Subfield('a', ''),
        pymarc.field.Subfield('y', '0123-4567'),
    ])
    record.add_field(bad_020)
    empty_020 = pymarc.Field(tag='020', indicators=[' ', ' '], subfields=[
        pymarc.field.Subfield('a', ''),
        pymarc.field.Subfield('y', ''),
    ])
    record.add_field(empty_020)
    good_035 = pymarc.Field(tag='035', indicators=[' ', ' '], subfields=[
        pymarc.field.Subfield('a', 'ocn123456789')
    ])
    record.add_field(good_035)
    bad_035 = pymarc.Field(tag='035', indicators=[' ', ' '], subfields=[
        pymarc.field.Subfield('a', '')
    ])
    record.add_field(bad_035)
    bad_650 = pymarc.Field(tag='650', indicators=[' ', ' '], subfields=[
        pymarc.field.Subfield('a', '')
    ])
    record.add_field(bad_650)
    good_650 = pymarc.Field(tag='650', indicators=[' ', ' '], subfields=[
        pymarc.field.Subfield('a', 'Test')
    ])
    record.add_field(good_650)
    bad_180 = pymarc.Field(tag='180', indicators=[' ', ' '], subfields=[
        pymarc.field.Subfield('x', '')
    ])
    record.add_field(bad_180)
    good_180 = pymarc.Field(tag='180', indicators=[' ', ' '], subfields=[
        pymarc.field.Subfield('x', 'Test')
    ])
    record.add_field(good_180)
    good_245 = pymarc.Field(tag='245', indicators=[' ', ' '], subfields=[
        pymarc.field.Subfield('a', 'Test: '),
        pymarc.field.Subfield('b', 'a test / '),
        pymarc.field.Subfield('c', 'by Test')
    ])
    record.add_field(good_245)
    record = processor.do_work(record)
    assert len(record.get_fields('010')) == 0
    assert len(record.get_fields('035')) == 1
    assert len(record.get_fields('650')) == 1
    assert len(record.get_fields('180')) == 1
    assert len(record.get_fields('245')) == 1
    assert len(record.get_fields('020')) == 1
    with pytest.raises(KeyError):
        record['020']['a']
    assert record["020"].get("y", "") == "0123-4567"

def test_fix_bib_leader():
    preprocessor = MARCPreprocessor("fix_bib_leader")
    record = pymarc.Record()
    record.leader = pymarc.Leader('01234mbm a2200349 a 4500')
    fields=[
        pymarc.Field(tag='001', data='123456'),
        pymarc.Field(tag='035', indicators=[' ', ' '], subfields=[
            pymarc.field.Subfield('a', 'ocn123456789')
        ]),
        pymarc.Field(tag='245', indicators=pymarc.Indicators(*[' ', ' ']), subfields=[
            pymarc.field.Subfield('a', 'Test: '),
            pymarc.field.Subfield('b', 'a test / '),
            pymarc.field.Subfield('c', 'by Test')
        ])
    ]
    for field in fields:
        record.add_field(field)
    record = preprocessor.do_work(record)
    assert record.leader[5] == 'c'
    assert record.leader[6] == 'a'


def test_clean_999_fields():
    preprocessor = MARCPreprocessor("clean_999_fields")
    record = pymarc.Record()
    record.add_field(pymarc.Field(tag='001', data='123456'))
    record.add_field(pymarc.Field(tag='999', indicators=['f', 'f'], subfields=[
        pymarc.field.Subfield('i', 'Test')
    ]))
    record.add_field(pymarc.Field(tag='999', indicators=[' ', ' '], subfields=[
        pymarc.field.Subfield('i', 'Test')
    ]))
    record = preprocessor.do_work(record)
    assert len(record.get_fields('999')) == 0
    assert len(record.get_fields('945')) == 1
    assert record['945'].indicators == pymarc.Indicators(*[' ', ' '])


def test_clean_non_ff_999_fields():
    preprocessor = MARCPreprocessor("clean_non_ff_999_fields")
    record = pymarc.Record()
    record.add_field(pymarc.Field(tag='001', data='123456'))
    record.add_field(pymarc.Field(tag='999', indicators=['f', 'f'], subfields=[
        pymarc.field.Subfield('i', 'Test')
    ]))
    record.add_field(pymarc.Field(tag='999', indicators=[' ', ' '], subfields=[
        pymarc.field.Subfield('i', 'Test')
    ]))
    record = preprocessor.do_work(record)
    assert len(record.get_fields('999')) == 1
    assert len(record.get_fields('945')) == 1


def test__get_preprocessor_functions():
    preprocessor_class = MARCPreprocessor("clean_999_fields,clean_empty_fields")
    assert preprocessor_class.preprocessors[0][0].__name__ == "clean_999_fields"
    assert preprocessor_class.preprocessors[1][0].__name__ == "clean_empty_fields"


def test_get_record_id_default_001():
    record = pymarc.Record()
    record.add_field(pymarc.Field(tag='001', data='123456'))
    assert _get_record_id(record) == '123456'


def test_get_record_id_custom_control_field():
    record = pymarc.Record()
    record.add_field(pymarc.Field(tag='003', data='OCoLC'))
    assert _get_record_id(record, record_id_field='003') == 'OCoLC'


def test_get_record_id_custom_field_with_subfield():
    record = pymarc.Record()
    record.add_field(pymarc.Field(tag='907', indicators=[' ', ' '], subfields=[
        pymarc.field.Subfield('a', '.b123456789')
    ]))
    assert _get_record_id(record, record_id_field='907', record_id_subfield='a') == '.b123456789'


def test_get_record_id_field_absent_returns_unknown():
    record = pymarc.Record()
    assert _get_record_id(record) == 'UNKNOWN'


def test_get_record_id_subfield_absent_returns_unknown():
    record = pymarc.Record()
    record.add_field(pymarc.Field(tag='907', indicators=[' ', ' '], subfields=[
        pymarc.field.Subfield('b', 'something')
    ]))
    assert _get_record_id(record, record_id_field='907', record_id_subfield='a') == 'UNKNOWN'


def test_get_record_id_empty_field_value_returns_unknown():
    record = pymarc.Record()
    record.add_field(pymarc.Field(tag='001', data=''))
    assert _get_record_id(record) == 'UNKNOWN'


def test_get_record_id_extra_kwargs_ignored():
    record = pymarc.Record()
    record.add_field(pymarc.Field(tag='001', data='123456'))
    assert _get_record_id(record, some_other_kwarg='foo') == '123456'


# --- preprocessors using record_id_field / record_id_subfield ---

def test_clean_non_ff_999_fields_custom_record_id(caplog):
    """Preprocessor logs the 907$a value as identifier when 001 is absent."""
    preprocessor = MARCPreprocessor(
        "clean_non_ff_999_fields",
        default={"record_id_field": "907", "record_id_subfield": "a"},
    )
    record = pymarc.Record()
    record.add_field(pymarc.Field(tag='907', indicators=[' ', ' '], subfields=[
        pymarc.field.Subfield('a', '.b987654321')
    ]))
    record.add_field(pymarc.Field(tag='999', indicators=[' ', ' '], subfields=[
        pymarc.field.Subfield('i', 'Test')
    ]))
    with caplog.at_level(26):
        record = preprocessor.do_work(record)
    assert '.b987654321' in caplog.text
    assert len(record.get_fields('945')) == 1


def test_fix_bib_leader_custom_record_id(caplog):
    """Preprocessor logs the 907$a value as identifier when 001 is absent."""
    preprocessor = MARCPreprocessor(
        "fix_bib_leader",
        default={"record_id_field": "907", "record_id_subfield": "a"},
    )
    record = pymarc.Record()
    record.leader = pymarc.Leader('01234mbm a2200349 a 4500')
    record.add_field(pymarc.Field(tag='907', indicators=[' ', ' '], subfields=[
        pymarc.field.Subfield('a', '.b111222333')
    ]))
    with caplog.at_level(26):
        record = preprocessor.do_work(record)
    assert '.b111222333' in caplog.text
    assert record.leader[5] == 'c'
    assert record.leader[6] == 'a'


def test_preprocessor_logs_unknown_when_id_field_absent(caplog):
    """Falls back to UNKNOWN when neither 001 nor the configured field is present."""
    preprocessor = MARCPreprocessor("clean_non_ff_999_fields")
    record = pymarc.Record()
    record.add_field(pymarc.Field(tag='999', indicators=[' ', ' '], subfields=[
        pymarc.field.Subfield('i', 'Test')
    ]))
    with caplog.at_level(26):
        record = preprocessor.do_work(record)
    assert 'UNKNOWN' in caplog.text


# --- normalize_subfield_codes ---

def test_normalize_subfield_codes_lowercases_uppercase_codes():
    record = pymarc.Record()
    record.add_field(pymarc.Field(tag='245', indicators=[' ', ' '], subfields=[
        pymarc.field.Subfield('A', 'Test title'),
        pymarc.field.Subfield('B', 'subtitle'),
    ]))
    result = normalize_subfield_codes(record)
    subfields = result['245'].subfields
    assert all(sf.code == sf.code.lower() for sf in subfields)
    assert subfields[0].code == 'a'
    assert subfields[1].code == 'b'


def test_normalize_subfield_codes_logs_data_issue_for_uppercase(caplog):
    record = pymarc.Record()
    record.add_field(pymarc.Field(tag='001', data='12345'))
    record.add_field(pymarc.Field(tag='245', indicators=[' ', ' '], subfields=[
        pymarc.field.Subfield('A', 'Test title'),
    ]))
    with caplog.at_level(26):
        normalize_subfield_codes(record)
    assert '245$A' in caplog.text
    assert 'normalizing to $a' in caplog.text


def test_normalize_subfield_codes_no_log_for_already_lowercase(caplog):
    record = pymarc.Record()
    record.add_field(pymarc.Field(tag='245', indicators=[' ', ' '], subfields=[
        pymarc.field.Subfield('a', 'Test title'),
    ]))
    with caplog.at_level(26):
        normalize_subfield_codes(record)
    assert 'DATA ISSUE' not in caplog.text


def test_normalize_subfield_codes_preserves_values():
    record = pymarc.Record()
    record.add_field(pymarc.Field(tag='100', indicators=['1', ' '], subfields=[
        pymarc.field.Subfield('A', 'Smith, John,'),
        pymarc.field.Subfield('D', '1950-'),
    ]))
    result = normalize_subfield_codes(record)
    subfields = result['100'].subfields
    assert subfields[0].value == 'Smith, John,'
    assert subfields[1].value == '1950-'


def test_normalize_subfield_codes_preserves_order():
    record = pymarc.Record()
    record.add_field(pymarc.Field(tag='650', indicators=[' ', '0'], subfields=[
        pymarc.field.Subfield('A', 'History'),
        pymarc.field.Subfield('Z', 'France'),
        pymarc.field.Subfield('Y', '20th century'),
    ]))
    result = normalize_subfield_codes(record)
    codes = [sf.code for sf in result['650'].subfields]
    assert codes == ['a', 'z', 'y']


def test_normalize_subfield_codes_already_lowercase_unchanged():
    record = pymarc.Record()
    record.add_field(pymarc.Field(tag='035', indicators=[' ', ' '], subfields=[
        pymarc.field.Subfield('a', 'ocn123456789'),
    ]))
    result = normalize_subfield_codes(record)
    assert result['035']['a'] == 'ocn123456789'
    assert result['035'].subfields[0].code == 'a'


def test_normalize_subfield_codes_skips_control_fields():
    """Control fields (001-009) have no subfields; function should not raise."""
    record = pymarc.Record()
    record.add_field(pymarc.Field(tag='001', data='12345'))
    record.add_field(pymarc.Field(tag='245', indicators=[' ', ' '], subfields=[
        pymarc.field.Subfield('A', 'Test'),
    ]))
    result = normalize_subfield_codes(record)
    assert result['001'].data == '12345'
    assert result['245'].subfields[0].code == 'a'


def test_normalize_subfield_codes_mixed_case_multiple_fields():
    record = pymarc.Record()
    record.add_field(pymarc.Field(tag='100', indicators=['1', ' '], subfields=[
        pymarc.field.Subfield('A', 'Doe, Jane'),
    ]))
    record.add_field(pymarc.Field(tag='700', indicators=['1', ' '], subfields=[
        pymarc.field.Subfield('A', 'Smith, Bob'),
        pymarc.field.Subfield('E', 'editor'),
    ]))
    result = normalize_subfield_codes(record)
    assert result['100'].subfields[0].code == 'a'
    assert result['700'].subfields[0].code == 'a'
    assert result['700'].subfields[1].code == 'e'


def test_normalize_subfield_codes_via_preprocessor():
    preprocessor = MARCPreprocessor("normalize_subfield_codes")
    record = pymarc.Record()
    record.add_field(pymarc.Field(tag='245', indicators=['1', '0'], subfields=[
        pymarc.field.Subfield('A', 'A test title /'),
        pymarc.field.Subfield('C', 'by Jane Doe'),
    ]))
    result = preprocessor.do_work(record)
    assert result['245']['a'] == 'A test title /'
    assert result['245']['c'] == 'by Jane Doe'


# --- copy_240_to_245_if_no_245 ---

def test_copy_240_to_245_if_no_245_copies_when_missing_title(caplog):
    record = pymarc.Record()
    record.add_field(pymarc.Field(tag='001', data='12345'))
    record.add_field(pymarc.Field(tag='240', indicators=['1', '0'], subfields=[
        pymarc.field.Subfield('a', 'Uniform title'),
        pymarc.field.Subfield('k', 'Selections'),
    ]))

    with caplog.at_level(26):
        result = copy_240_to_245_if_no_245(record)

    fields_245 = result.get_fields('245')
    assert len(fields_245) == 1
    assert fields_245[0].indicators == pymarc.Indicators(*['0', '0'])
    assert [sf.code for sf in fields_245[0].subfields] == ['a', 'k']
    assert [sf.value for sf in fields_245[0].subfields] == ['Uniform title', 'Selections']
    assert 'No 245 field found: copying subfields from 240 to 245' in caplog.text


def test_copy_240_to_245_if_no_245_uses_first_240_when_multiple():
    record = pymarc.Record()
    record.add_field(pymarc.Field(tag='240', indicators=['1', '0'], subfields=[
        pymarc.field.Subfield('a', 'First uniform title'),
    ]))
    record.add_field(pymarc.Field(tag='240', indicators=['1', '0'], subfields=[
        pymarc.field.Subfield('a', 'Second uniform title'),
    ]))

    result = copy_240_to_245_if_no_245(record)

    assert len(result.get_fields('245')) == 1
    assert result['245']['a'] == 'First uniform title'


def test_copy_240_to_245_if_no_245_noop_when_245_exists():
    record = pymarc.Record()
    record.add_field(pymarc.Field(tag='240', indicators=['1', '0'], subfields=[
        pymarc.field.Subfield('a', 'Uniform title'),
    ]))
    record.add_field(pymarc.Field(tag='245', indicators=['1', '0'], subfields=[
        pymarc.field.Subfield('a', 'Display title'),
    ]))

    result = copy_240_to_245_if_no_245(record)

    assert len(result.get_fields('245')) == 1
    assert result['245']['a'] == 'Display title'


def test_copy_240_to_245_if_no_245_noop_without_240():
    record = pymarc.Record()

    result = copy_240_to_245_if_no_245(record)

    assert len(result.get_fields('245')) == 0


def test_copy_240_to_245_if_no_245_empty_subfield_245(caplog):
    record = pymarc.Record()
    record.add_field(pymarc.Field(tag='245', indicators=['1', '0'], subfields=[
        pymarc.field.Subfield('a', ''),
        pymarc.field.Subfield('b', ''),
    ]))
    record.add_field(pymarc.Field(tag='240', indicators=['1', '0'], subfields=[
        pymarc.field.Subfield('a', 'Uniform title'),
    ]))
    result = copy_240_to_245_if_no_245(record)

    assert len(result.get_fields('245')) == 1
    assert result['245']['a'] == 'Uniform title'


def test_copy_240_to_245_if_no_245_via_preprocessor_with_custom_record_id(caplog):
    preprocessor = MARCPreprocessor(
        "copy_240_to_245_if_no_245",
        default={"record_id_field": "907", "record_id_subfield": "a"},
    )
    record = pymarc.Record()
    record.add_field(pymarc.Field(tag='907', indicators=[' ', ' '], subfields=[
        pymarc.field.Subfield('a', '.b24681012'),
    ]))
    record.add_field(pymarc.Field(tag='240', indicators=['1', '0'], subfields=[
        pymarc.field.Subfield('a', 'Uniform title for import'),
    ]))

    with caplog.at_level(26):
        result = preprocessor.do_work(record)

    assert len(result.get_fields('245')) == 1
    assert result['245']['a'] == 'Uniform title for import'
    assert '.b24681012' in caplog.text
