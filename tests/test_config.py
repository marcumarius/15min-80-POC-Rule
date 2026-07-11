import yaml
import pytest

from config import ConfigError, load_config


def test_load_config_defaults():
    cfg = load_config()
    assert cfg.structural.va_percent == 0.70
    assert cfg.meta.instrument == "MNQ"
    assert cfg.filters.no_mans_land_atr == 0.5
    assert cfg.structural.overnight_vp_enable is False
    assert cfg.structural.level_stack_tol_ticks == 6


def test_out_of_range_default_raises(tmp_path):
    bad = {"structural": {"va_percent": {"default": 5.0, "range": [0.6, 0.8], "rationale": "x"}}}
    p = tmp_path / "bad.yaml"
    p.write_text(yaml.safe_dump(bad))
    with pytest.raises(ConfigError):
        load_config(p)


def test_in_range_default_does_not_raise(tmp_path):
    ok = {"structural": {"va_percent": {"default": 0.70, "range": [0.6, 0.8], "rationale": "x"}}}
    p = tmp_path / "ok.yaml"
    p.write_text(yaml.safe_dump(ok))
    cfg = load_config(p)
    assert cfg.structural.va_percent == 0.70


def test_dotted_access_missing_key_raises_attributeerror():
    cfg = load_config()
    with pytest.raises(AttributeError):
        _ = cfg.structural.does_not_exist


def test_non_mapping_top_level_raises(tmp_path):
    p = tmp_path / "list.yaml"
    p.write_text(yaml.safe_dump([1, 2, 3]))
    with pytest.raises(ConfigError):
        load_config(p)
