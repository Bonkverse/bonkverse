"""Custom error pages render with the site layout (templates/error_base.html)."""

import pytest


@pytest.mark.django_db
def test_404_page_renders_with_site_layout(client, settings):
    settings.DEBUG = False  # Django only uses 404.html when DEBUG is off

    response = client.get("/this-page-does-not-exist/")

    assert response.status_code == 404
    assert b"Page not found" in response.content
    assert b"css/errors.css" in response.content


class TestServerError:
    """Production ran with DEBUG_PROPAGATE_EXCEPTIONS=True, so an unhandled error
    skipped Django's error handling: no 500 page, and with Django's default
    logging nothing was written unless DEBUG was on."""

    @pytest.fixture
    def crashing_client(self, client, settings):
        settings.DEBUG = False
        settings.ROOT_URLCONF = "tests.urls_with_crash"
        client.raise_request_exception = False
        return client

    def test_unhandled_error_shows_the_500_page(self, crashing_client):
        response = crashing_client.get("/__crash__/")

        assert response.status_code == 500
        assert b"Something went wrong" in response.content
        assert b"boom" not in response.content  # no internals shown to visitors

    def test_unhandled_error_is_logged_with_traceback(self, crashing_client, caplog):
        with caplog.at_level("ERROR", logger="django.request"):
            crashing_client.get("/__crash__/")

        [record] = [r for r in caplog.records if r.name == "django.request"]
        assert record.exc_info and "deliberate test crash" in str(record.exc_info[1])

    def test_500_page_works_without_static_files_or_database(self, crashing_client, monkeypatch):
        """2026-11-03: error pages that used {% static %} crashed again when the
        static files manifest was missing. The 500 page must not depend on it."""

        def no_manifest(*args, **kwargs):
            raise ValueError("Missing staticfiles manifest entry")

        monkeypatch.setattr("django.templatetags.static.static", no_manifest)
        monkeypatch.setattr("django.templatetags.static.StaticNode.url", no_manifest)

        response = crashing_client.get("/__crash__/")

        assert response.status_code == 500
        assert b"Something went wrong" in response.content


def test_production_settings_do_not_propagate_exceptions(settings):
    assert settings.DEBUG_PROPAGATE_EXCEPTIONS is False


def test_errors_and_app_logs_reach_stdout(settings):
    loggers = settings.LOGGING["loggers"]

    assert loggers["django.request"]["handlers"] == ["console"]
    assert loggers["skins"]["handlers"] == ["console"]
    assert settings.LOGGING["handlers"]["console"]["class"] == "logging.StreamHandler"
