"""Unit tests for DataValidator field-correction validation."""

from app.domain.validator import DataValidator


def test_validate_docente_handles_none_email():
    """
    Regression test: parsed docenti store email=None when the CSV field is
    empty (see CalendarParser.parse_docenti_csv), and
    `docente.get("email", "").strip()` crashes on None because dict.get's
    default only applies when the key is missing, not when its value is
    None.
    """
    docente = {"nome": "Prof Beta", "email": None, "tipo": "CONTRATTO"}
    valid, error = DataValidator.validate_docente(docente)
    assert valid is True
    assert error == ""


def test_validate_docente_rejects_bad_email():
    docente = {"nome": "Prof Beta", "email": "not-an-email", "tipo": "CONTRATTO"}
    valid, error = DataValidator.validate_docente(docente)
    assert valid is False
    assert "email" in error.lower()


def test_validate_docente_rejects_bad_tipo():
    docente = {"nome": "Prof Beta", "email": None, "tipo": "STAGISTA"}
    valid, error = DataValidator.validate_docente(docente)
    assert valid is False


def test_validate_all_data_flags_dangling_assignment():
    valid, errors = DataValidator.validate_all_data(
        docenti=[{"nome": "Prof Alfa"}],
        classi=[{"nome": "1A"}],
        materie=[{"nome": "Matematica"}],
        assegnazioni=[{"docente_nome": "Prof Sconosciuto", "classe_nome": "1A", "materia_nome": "Matematica"}],
        accoppiamenti=[],
        calendario=[],
    )
    assert valid is False
    assert any("Prof Sconosciuto" in e for e in errors)
