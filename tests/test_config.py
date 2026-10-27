"""默认配置不依赖 PyYAML；只有真的要读 YAML 时才要求它。"""

from __future__ import annotations

import pytest

from ltm.core import config as config_mod


def test_defaults_load_without_pyyaml(monkeypatch) -> None:
    monkeypatch.setattr(config_mod, "yaml", None)
    settings = config_mod.load_settings(None)
    assert settings["schema_version"] == 3
    assert settings["members"]


def test_yaml_path_without_pyyaml_fails_loudly(monkeypatch) -> None:
    monkeypatch.setattr(config_mod, "yaml", None)
    with pytest.raises(RuntimeError, match="PyYAML"):
        config_mod.load_settings("no-such-override.yaml")
