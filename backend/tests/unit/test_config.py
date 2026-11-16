import pytest
from pydantic import ValidationError

from app.core.config import Settings

STRONG = {
    "jwt_secret": "k" * 64,
    "cookie_secure": True,
    "postgres_owner_password": "Owner-Strong-Pass-123456",
    "postgres_app_password": "App-Strong-Pass-1234567",
}


def _settings(**overrides: object) -> Settings:
    # _env_file=None: ignore the developer's .env so the test is deterministic.
    return Settings(_env_file=None, **{**STRONG, **overrides})  # type: ignore[arg-type]


def test_production_accepts_strong_config() -> None:
    assert _settings(app_env="production").is_production


@pytest.mark.parametrize(
    "overrides",
    [
        {"jwt_secret": "change-me-to-a-long-random-string-xxxxxxxxxxxxxxxxx"},
        {"jwt_secret": "x" * 40},
        {"cookie_secure": False},
        {"postgres_app_password": "csp_app_dev_password"},
    ],
)
def test_production_rejects_unsafe_config(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError, match="Unsafe production configuration"):
        _settings(app_env="production", **overrides)


def test_development_allows_dev_values() -> None:
    assert not _settings(app_env="development", cookie_secure=False).is_production


def test_database_url_escapes_password_and_hides_it() -> None:
    s = _settings(postgres_app_password="it's@a:p/w#%")
    url = s.app_database_url
    assert url.password == "it's@a:p/w#%"  # parsed back exactly
    assert "p/w" not in str(url)  # masked when printed or logged
    rendered = url.render_as_string(hide_password=False)
    assert "@127.0.0.1" in rendered and rendered.count("@") == 1  # '@' was escaped
