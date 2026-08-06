""".env.example 与 Settings 字段互检守卫（EN-10）。

Settings 新增字段但未在 .env.example 登记时测试失败，防止配置漂移。
"""

from pathlib import Path

from app.config.settings import Settings

_ENV_EXAMPLE = Path(__file__).resolve().parents[2] / ".env.example"


def _env_example_keys() -> set[str]:
    keys: set[str] = set()
    for line in _ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        keys.add(stripped.split("=", 1)[0].strip())
    return keys


def _settings_env_names() -> set[str]:
    names: set[str] = set()
    for field_name, field in Settings.model_fields.items():
        # pydantic-settings 无显式 alias 时环境变量名 = 字段名大写
        names.add((field.alias or field_name).upper())
    return names


def test_every_settings_field_is_documented_in_env_example() -> None:
    documented = _env_example_keys()
    missing = sorted(_settings_env_names() - documented)
    assert not missing, f".env.example 缺少以下 Settings 字段登记: {missing}"
