import pytest

from ltm.core.errors import DuplicatePluginError
from ltm.core.registry import available, create, register


def test_register_and_reject_duplicate():
    @register("demo", "alpha")
    def build():
        return "alpha"

    assert create("demo", "alpha") == "alpha"
    assert "alpha" in available("demo")
    with pytest.raises(DuplicatePluginError):
        register("demo", "alpha")(build)
