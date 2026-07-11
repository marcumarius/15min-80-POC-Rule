"""Config loader: single source of truth for all strategy parameters.

Loads params.yaml, validates types/ranges, exposes a typed Config object.
See CLAUDE.md section 4 and config/params.yaml. Changing a default requires a
Decision Log entry (docs/decisions.md).

Phase 1 deliverable (docs/phase1_foundation_engine.md section 3.5).
"""
from pathlib import Path
import yaml

_PARAMS = Path(__file__).parent / "params.yaml"


class ConfigError(ValueError):
    """Raised when a params.yaml value is missing, malformed, or out of range."""


class Section:
    """Dotted-access, read-only view over one validated parameter section."""

    def __init__(self, values: dict):
        self.__dict__["_values"] = values

    def __getattr__(self, name):
        try:
            return self._values[name]
        except KeyError:
            raise AttributeError(name) from None

    def __getitem__(self, name):
        return self._values[name]

    def __repr__(self):
        return f"Section({self._values!r})"


class Config:
    """Typed, validated, dotted-access view over params.yaml.

    Every `{default, range, rationale}` leaf collapses to its default value,
    e.g. `cfg.structural.va_percent` -> 0.70.
    """

    def __init__(self, raw: dict):
        for section_name, section in raw.items():
            setattr(self, section_name, Section(_resolve(section)))

    def __repr__(self):
        return f"Config({list(self.__dict__)!r})"


def _resolve(node):
    """Collapse a {default, range, rationale} leaf to its default value."""
    if isinstance(node, dict) and "default" in node:
        return node["default"]
    if isinstance(node, dict):
        return {k: _resolve(v) for k, v in node.items()}
    return node


def _validate(node, path=""):
    """Walk params.yaml and raise ConfigError on any out-of-range default."""
    if not isinstance(node, dict):
        return
    if "default" in node:
        _validate_range(path, node["default"], node.get("range"))
        return
    for key, val in node.items():
        _validate(val, f"{path}.{key}" if path else key)


def _validate_range(path, value, rng):
    if rng is None:
        return
    if isinstance(value, list):
        for v in value:
            _validate_range(path, v, rng)
        return
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return  # range bounds only apply to numeric knobs
    lo, hi = rng
    if not (lo <= value <= hi):
        raise ConfigError(f"{path}: default {value!r} out of documented range {rng}")


def load_config(path: Path = _PARAMS) -> Config:
    """Load params.yaml, validate every default against its documented range,
    and return a typed Config with dotted section access."""
    with open(path) as f:
        raw = yaml.safe_load(f)
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: expected a top-level mapping")
    _validate(raw)
    return Config(raw)
