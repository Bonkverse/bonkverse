"""Tests for the upload form (skins/views/upload.py).

The import itself (fetch, SVG check, storage, duplicates) is
skins/skin_import.py, tested in test_bot_skins.py; these pin what the form
adds on top and what people see.
"""

import base64

import pytest
import requests

from skins.models import Skin, SkinImage
from accounts.models import UserEvent
from tests.factories import SkinFactory, UserFactory

pytestmark = pytest.mark.django_db

URL = "/upload/"
FETCHER = "https://fetcher.test/api/getSkin"
LINK = "https://bonkleagues.io/s/AbC1234"
SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10">'
    '<rect width="10" height="10" fill="red"/></svg>'
)
PNG = b"\x89PNG fake"


@pytest.fixture(autouse=True)
def _settings(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    settings.BLSKIN_FETCHER_URL = FETCHER


@pytest.fixture
def user_client(client):
    client.force_login(UserFactory(username=" Spaced  Uploader"))
    return client


def _fetcher_replies(mocked_http, svg=SVG, author=None, **kwargs):
    body = {
        "skinCode": "CODE123",
        "media": {"svg": svg, "pngBase64": base64.b64encode(PNG).decode()},
        "name": "Fire Dragon",
        "author": author,
    }
    return mocked_http.get(FETCHER, **({"json": body} | kwargs))


def _upload(client, **fields):
    return client.post(URL, {"skin_name": "Fire Dragon", "bonkleagues_link": LINK, **fields})


def _messages(response):
    return [str(m) for m in response.context["messages"]]


def test_creates_skin_with_files_and_redirects_to_search(user_client, mocked_http, tmp_path):
    _fetcher_replies(mocked_http)

    response = _upload(user_client)

    skin = Skin.objects.get()
    assert response.status_code == 302
    assert response["Location"] == f"/search/?q=Fire+Dragon&new={skin.id}"
    assert skin.creator == " Spaced  Uploader"  # never trimmed
    assert (skin.name, skin.link, skin.skin_code) == ("Fire Dragon", LINK, "CODE123")
    assert (tmp_path / f"skins/{skin.id}.svg").read_text() == SVG
    assert SkinImage.objects.filter(skin=skin).count() == 3
    assert UserEvent.objects.filter(event_type="skin_uploaded").count() == 1
    assert skin.submitted_by.username == " Spaced  Uploader"
    assert (skin.submission_source, skin.creator_source) == ("website", "submitter")


def test_link_already_on_site_in_another_spelling_is_a_duplicate(user_client, mocked_http):
    SkinFactory(link="http://www.bonkleagues.io/s/AbC1234/")

    response = _upload(user_client)

    assert response.status_code == 302
    assert response["Location"] == URL
    assert Skin.objects.count() == 1
    assert len(mocked_http.calls) == 0  # nothing fetched for a duplicate


@pytest.mark.parametrize(
    "kwargs",
    [
        {"body": requests.ConnectionError("fetcher at 10.0.0.9 refused")},
        {"json": {"error": "Puppeteer stack trace"}, "status": 500},
    ],
)
def test_fetcher_failure_shows_a_sentence_not_service_details(user_client, mocked_http, kwargs):
    """Regression: the message used to include the raw exception text."""
    mocked_http.get(FETCHER, **kwargs)

    response = _upload(user_client)

    assert response.status_code == 200
    [message] = _messages(response)
    assert message.startswith("Couldn't get that skin from BonkLeagues right now.")
    assert "10.0.0.9" not in message and "Puppeteer" not in message
    assert not Skin.objects.exists()


def test_unsafe_svg_is_rejected_without_details(user_client, mocked_http):
    _fetcher_replies(mocked_http, svg='<svg xmlns="http://www.w3.org/2000/svg"><script/></svg>')

    response = _upload(user_client)

    assert _messages(response) == [
        "This skin's image failed our SVG safety check, so it wasn't added."
    ]
    assert not Skin.objects.exists()


def test_oversized_svg_says_too_detailed(user_client, mocked_http):
    _fetcher_replies(mocked_http, svg=SVG.replace("</svg>", "<!--" + "x" * 2_000_000 + "--></svg>"))

    response = _upload(user_client)

    assert "too detailed" in _messages(response)[0]
    assert not Skin.objects.exists()


@pytest.mark.parametrize(
    "fields,message",
    [
        ({"skin_name": ""}, "All fields are required."),
        ({"skin_name": "Fire🔥"}, "Skin name can only contain"),
        ({"bonkleagues_link": "https://bonkleagues.io/s/short"}, "Invalid Bonkleagues link"),
        ({"bonkleagues_link": "https://evil.example/s/AbC1234"}, "Invalid Bonkleagues link"),
    ],
)
def test_form_rules_reject_before_fetching(user_client, mocked_http, fields, message):
    response = _upload(user_client, **fields)

    assert _messages(response)[0].startswith(message)
    assert len(mocked_http.calls) == 0


def test_anonymous_is_sent_to_login(client):
    response = _upload(client)

    assert response.status_code == 302
    assert response["Location"].startswith("/login/")


# --- "Did you make this skin?" --------------------------------------------------


def _fetch_count(mocked_http):
    return sum(1 for call in mocked_http.calls if call.request.url.startswith(FETCHER))


def test_bonkleagues_author_matching_uploader_in_any_case_is_not_asked(user_client, mocked_http):
    _fetcher_replies(mocked_http, author=" spaced  UPLOADER")  # bonk.io keeps the spaces

    response = _upload(user_client)

    assert response.status_code == 302
    skin = Skin.objects.get()
    assert (skin.creator, skin.creator_source) == (" Spaced  Uploader", "submitter")


def test_other_bonkleagues_author_asks_before_saving(user_client, mocked_http):
    _fetcher_replies(mocked_http, author="Somepoop")

    response = _upload(user_client)

    assert response.status_code == 200
    assert not Skin.objects.exists()
    assert response.context["creator_check"] == {
        "author": "Somepoop",
        "skin_name": "Fire Dragon",
        "link": LINK,
    }
    html = response.content.decode()
    assert 'id="creator-check"' in html
    assert "BonkLeagues credits this skin to <strong>Somepoop</strong>" in html
    assert 'name="made_it" value="yes"' in html and 'name="made_it" value="no"' in html


def test_i_made_it_credits_the_uploader_without_fetching_again(user_client, mocked_http):
    _fetcher_replies(mocked_http, author="Somepoop")
    _upload(user_client)

    response = _upload(user_client, made_it="yes")

    assert response.status_code == 302
    skin = Skin.objects.get()
    assert (skin.creator, skin.creator_source) == (" Spaced  Uploader", "submitter")
    assert _fetch_count(mocked_http) == 1  # the answer was remembered between the two posts


def test_not_mine_credits_the_bonkleagues_author_and_records_the_uploader(user_client, mocked_http):
    _fetcher_replies(mocked_http, author="Somepoop")

    response = _upload(user_client, made_it="no")

    skin = Skin.objects.get()
    assert (skin.creator, skin.creator_source) == ("Somepoop", "bonkleagues")
    assert skin.submitted_by.username == " Spaced  Uploader"
    assert skin.submission_source == "website"
    follow = user_client.get(response["Location"])
    assert _messages(follow) == [
        "Skin uploaded! It's credited to Somepoop, and you're listed as the uploader."
    ]


def test_an_unknown_answer_asks_again(user_client, mocked_http):
    _fetcher_replies(mocked_http, author="Somepoop")

    response = _upload(user_client, made_it="maybe")

    assert response.status_code == 200
    assert "creator_check" in response.context
    assert not Skin.objects.exists()


def test_no_bonkleagues_author_credits_the_uploader(user_client, mocked_http):
    _fetcher_replies(mocked_http, author="   ")

    _upload(user_client)

    skin = Skin.objects.get()
    assert (skin.creator, skin.creator_source) == (" Spaced  Uploader", "submitter")


def test_duplicate_link_is_refused_before_fetching(user_client, mocked_http):
    SkinFactory(link=LINK)

    response = _upload(user_client)

    assert response["Location"] == URL
    assert _fetch_count(mocked_http) == 0


def test_dialog_values_are_escaped(user_client, mocked_http):
    _fetcher_replies(mocked_http, author='<b>"x"</b>')

    html = _upload(user_client).content.decode()

    assert "<b>" not in html.split('id="creator-check"', 1)[1]
