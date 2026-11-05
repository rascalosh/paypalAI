import pytest

from app.config import normalize_db_url


@pytest.mark.parametrize(
    "raw",
    [
        "postgres://u:p@h:5432/d",
        "postgresql://u:p@h:5432/d",
        "postgresql+psycopg://u:p@h:5432/d",
    ],
)
def test_normalize_db_url(raw):
    assert normalize_db_url(raw) == "postgresql+psycopg://u:p@h:5432/d"
