"""Settings added by #8 (instance mode, the local administrator's credentials) and #9 (invitation
delay, minimum password length)."""

from datetime import timedelta

import pytest

from app.config import (
    DEFAULT_INVITATION_VALIDITY_HOURS,
    DEFAULT_PASSWORD_MIN_LENGTH,
    MAX_SETTING_NUMBER,
    ConfigurationError,
    load_settings,
)


def test_invitation_delay_and_password_minimum_are_read_by_name() -> None:
    settings = load_settings({"INVITATION_VALIDITY_HOURS": " 30 ", "PASSWORD_MIN_LENGTH": "9"})

    assert settings.invitation_validity == timedelta(hours=30)
    assert settings.password_min_length == 9


def test_invitation_delay_and_password_minimum_have_local_defaults() -> None:
    settings = load_settings({"INVITATION_VALIDITY_HOURS": "", "PASSWORD_MIN_LENGTH": " "})

    assert settings.invitation_validity == timedelta(hours=DEFAULT_INVITATION_VALIDITY_HOURS)
    assert settings.password_min_length == DEFAULT_PASSWORD_MIN_LENGTH


@pytest.mark.parametrize("name", ["INVITATION_VALIDITY_HOURS", "PASSWORD_MIN_LENGTH"])
@pytest.mark.parametrize("value", ["0", "-4", "1.5", "ten", "²", "99999999999999999999"])
def test_invalid_numbers_name_the_setting_not_the_value(name: str, value: str) -> None:
    with pytest.raises(ConfigurationError) as raised:
        load_settings({name: value})

    # The name and the accepted range only, never the submitted value.
    assert str(raised.value) == f"{name} must be a whole number between 1 and {MAX_SETTING_NUMBER}"


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


def test_the_country_table_and_the_buyer_text_limits_are_read_by_name() -> None:
    default = load_settings({})
    custom = load_settings(
        {
            "COUNTRY_TABLE_FILE": " /tables/countries.json ",
            "CRITERIA_MAX_CHARS": "300",
            "BUYER_NOTES_MAX_CHARS": "50",
            "BUYER_TEXT_MAX_CHARS": "700",
        }
    )

    assert default.country_table_file is None
    assert (default.criteria_max_chars, default.buyer_notes_max_chars) == (2000, 1000)
    assert custom.country_table_file == "/tables/countries.json"
    assert (custom.criteria_max_chars, custom.buyer_notes_max_chars) == (300, 50)
    assert custom.buyer_text_max_chars == 700
    with pytest.raises(ConfigurationError, match="CRITERIA_MAX_CHARS"):
        load_settings({"CRITERIA_MAX_CHARS": "0"})


def test_worker_settings_have_defaults_and_are_validated() -> None:
    default = load_settings({})
    custom = load_settings({"RUN_LEASE_SECONDS": "45", "WORKER_POLL_SECONDS": "1"})

    assert (default.run_lease.total_seconds(), default.worker_poll_seconds) == (300, 2)
    assert (custom.run_lease.total_seconds(), custom.worker_poll_seconds) == (45, 1)
    with pytest.raises(ConfigurationError, match="RUN_LEASE_SECONDS"):
        load_settings({"RUN_LEASE_SECONDS": "0"})


def test_the_comparison_maximum_is_a_setting_with_a_local_default() -> None:
    default = load_settings({})
    custom = load_settings({"COMPARISON_MAX_PROFILES": "4"})

    assert default.comparison_max_profiles == 10
    assert custom.comparison_max_profiles == 4
    for value in ("1", "0", "many", "-3"):
        with pytest.raises(ConfigurationError, match="COMPARISON_MAX_PROFILES"):
            load_settings({"COMPARISON_MAX_PROFILES": value})
