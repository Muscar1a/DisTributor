import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))

from smoke_admin_api import origin_only  # noqa: E402


def test_origin_only_accepts_render_origin():
    assert origin_only("https://gateway.onrender.com/", "gateway") == "https://gateway.onrender.com"


@pytest.mark.parametrize(
    "value",
    [
        "https://gateway.onrender.com/admin",
        "https://gateway.onrender.com?key=secret",
        "https://admin:secret@gateway.onrender.com",
        "http://gateway.onrender.com",
    ],
)
def test_origin_only_rejects_unsafe_production_values(value):
    with pytest.raises(ValueError):
        origin_only(value, "gateway")
