from pathlib import Path

from click.testing import CliRunner

from validate_schema import cli, validate_metamodel, validate_references

FIXTURES = Path(__file__).parent / "fixtures"


def test_class_with_slots_is_valid():
    path = str(FIXTURES / "valid_slots.yml")
    assert validate_metamodel(path) == []
    assert validate_references(path) == []


def test_class_with_attributes_is_valid():
    path = str(FIXTURES / "valid_attributes.yml")
    assert validate_metamodel(path) == []
    assert validate_references(path) == []


def test_undefined_slot_fails_reference_check():
    path = str(FIXTURES / "invalid_undefined_slot.yml")
    assert validate_metamodel(path) == []  # shape is fine — only the reference is broken
    errors = validate_references(path)
    assert errors
    assert any("nonexistent_slot" in e for e in errors)


def test_cli_accepts_valid_schema():
    result = CliRunner().invoke(cli, [str(FIXTURES / "valid_slots.yml")])
    assert result.exit_code == 0
    assert "Valid LinkML schema" in result.output


def test_cli_rejects_undefined_slot():
    result = CliRunner().invoke(cli, [str(FIXTURES / "invalid_undefined_slot.yml")])
    assert result.exit_code != 0
    assert "nonexistent_slot" in result.output
