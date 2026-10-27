"""Settings added by #8: instance mode and the local administrator's credentials."""

import pytest

from app.config import ConfigurationError, load_settings


def test_instance_mode_defaults_to_self_hosted() -> None:
    settings = load_settings({})

    assert settings.instance_mode == "self_hosted"
    assert settings.organisations_skip_activation is True


def test_hosted_instance_mode() -> None:
    settings = load_settings({"INSTANCE_MODE": "hosted"})

    assert settings.instance_mode == "hosted"
    assert settings.organisations_skip_activation is False


def test_invalid_instance_mode_names_the_setting() -> None:
    with pytest.raises(ConfigurationError, match="INSTANCE_MODE") as raised:
        load_settings({"INSTANCE_MODE": "cloud-xyz"})

    assert "cloud-xyz" not in str(raised.value)


def test_administrator_settings_are_read_by_name() -> None:
    settings = load_settings({"ADMIN_EMAIL": " admin@example.test ", "ADMIN_PASSWORD": " p w "})

    assert settings.admin_email == "admin@example.test"
    assert settings.admin_password == " p w "  # spaces are part of a password


def test_empty_administrator_settings_count_as_missing() -> None:
    settings = load_settings({"ADMIN_EMAIL": "  ", "ADMIN_PASSWORD": ""})

    assert settings.admin_email is None
    assert settings.admin_password is None


def test_settings_repr_hides_secrets() -> None:
    settings = load_settings(
        {
            "DATABASE_URL": "postgresql://user:db-secret@db/name",
            "ADMIN_PASSWORD": "admin-secret",
        }
    )

    assert "db-secret" not in repr(settings)
    assert "admin-secret" not in repr(settings)
