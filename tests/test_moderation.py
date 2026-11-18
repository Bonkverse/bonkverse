"""Staff report queue (/moderation/, skins/moderation.py).

One page shows each reported skin with all its open reports; one button makes
a decision and closes every open report on the skin; each decision is
recorded (ModerationDecision) with what notifications will need later.
"""

import pytest
from django.core.exceptions import ValidationError

from skins import moderation
from skins.models import CreatorSource, ModerationDecision, Skin, SkinReport
from tests.factories import SkinFactory, SkinReportFactory, UserFactory

pytestmark = pytest.mark.django_db

URL = "/moderation/"


@pytest.fixture
def staff(db):
    return UserFactory(is_staff=True)


@pytest.fixture
def staff_client(client, staff):
    client.force_login(staff)
    return client


def _decide(client, skin, action, **fields):
    return client.post(f"/moderation/skins/{skin.id}/decide/", {"action": action, **fields})


# ── Who can see it ───────────────────────────────────────────────────


def test_signed_out_visitors_are_sent_to_log_in(client):
    response = client.get(URL)

    assert response.status_code == 302
    assert response["Location"].startswith("/login/?next=/moderation/")


def test_signed_in_non_staff_get_a_404(client):
    skin = SkinFactory()
    client.force_login(UserFactory())

    assert client.get(URL).status_code == 404
    assert _decide(client, skin, "delete").status_code == 404
    assert Skin.objects.filter(id=skin.id).exists()


def test_staff_see_the_link_in_the_account_menu(staff_client):
    assert 'href="/moderation/"' in staff_client.get("/").content.decode()


def test_others_dont_see_the_link(client):
    client.force_login(UserFactory())

    assert 'href="/moderation/"' not in client.get("/").content.decode()


# ── The queue ────────────────────────────────────────────────────────


def test_queue_groups_open_reports_by_skin_most_reported_first(staff_client):
    once = SkinFactory(name="Once", image_url="/media/skins/once.png")
    thrice = SkinFactory(name="Thrice")
    SkinReportFactory(skin=once)
    SkinReportFactory.create_batch(2, skin=thrice, reason="stolen")
    SkinReportFactory(skin=thrice, reason="spam", details="copied from zorro")
    SkinReportFactory(skin=SkinFactory(name="Done"), resolved=True)

    response = staff_client.get(URL)
    skins = response.context["skins"]

    assert [s.name for s in skins] == ["Thrice", "Once"]
    assert skins[0].open_report_count == 3
    assert skins[0].reason_counts == [
        ("Stolen / reposted without credit", 2),
        ("Spam or low-effort", 1),
    ]
    html = response.content.decode()
    assert 'src="/media/skins/once.png"' in html
    assert "copied from zorro" in html
    assert "Done" not in html


def test_queue_is_a_fixed_number_of_queries(staff_client, django_assert_max_num_queries):
    for _ in range(10):
        skin = SkinFactory()
        SkinReportFactory(skin=skin, reporter=UserFactory())
        SkinReportFactory(skin=skin, reporter=UserFactory())

    with django_assert_max_num_queries(10):
        staff_client.get(URL)


def test_empty_queue_says_so(staff_client):
    html = staff_client.get(URL).content.decode()

    assert "No open reports" in html


# ── Decisions ────────────────────────────────────────────────────────


def test_keep_closes_every_open_report_and_records_it(staff_client, staff):
    reporter = UserFactory()
    skin = SkinFactory()
    SkinReportFactory(skin=skin, reporter=reporter, reason="stolen")
    SkinReportFactory(skin=skin, reason="spam")  # anonymous

    response = _decide(staff_client, skin, "dismiss", note="it's fine")

    assert response.status_code == 302
    decision = ModerationDecision.objects.get()
    assert decision.action == "dismissed"
    assert decision.decided_by == staff
    assert decision.report_count == 2
    assert decision.reasons == ["stolen", "spam"]
    assert decision.reporter_ids == [reporter.id]
    assert decision.note == "it's fine"
    assert not SkinReport.objects.filter(resolved=False).exists()
    assert set(SkinReport.objects.values_list("decision", flat=True)) == {decision.id}
    assert list(Skin.objects.without_open_reports()) == [skin]


def test_change_creator_credits_the_new_name_and_closes_reports(staff_client):
    skin = SkinFactory(creator="Thief")
    SkinReportFactory(skin=skin, reason="stolen")

    _decide(staff_client, skin, "change_creator", creator="  Isabelle26 ")

    skin.refresh_from_db()
    assert skin.creator == "Isabelle26"
    assert skin.creator_source == CreatorSource.STAFF
    decision = ModerationDecision.objects.get()
    assert (decision.old_creator, decision.new_creator) == ("Thief", "Isabelle26")
    assert not SkinReport.objects.filter(resolved=False).exists()


@pytest.mark.parametrize("name", ["", "Thief", "thief"])
def test_change_creator_refuses_an_empty_or_unchanged_name(staff_client, name):
    skin = SkinFactory(creator="Thief")
    SkinReportFactory(skin=skin)

    response = _decide(staff_client, skin, "change_creator", creator=name)

    assert response.status_code == 302
    assert SkinReport.objects.filter(resolved=False).count() == 1  # nothing changed
    assert not ModerationDecision.objects.exists()
    messages = [str(m) for m in staff_client.get(URL).context["messages"]]
    assert messages and messages[0]


def test_delete_removes_the_skin_but_keeps_the_record(staff_client):
    reporter = UserFactory()
    skin = SkinFactory(name="Bad", creator="Someone")
    SkinReportFactory(skin=skin, reporter=reporter)

    _decide(staff_client, skin, "delete")

    assert not Skin.objects.filter(id=skin.id).exists()
    decision = ModerationDecision.objects.get()
    assert (decision.skin, decision.skin_name, decision.action) == (None, "Bad", "deleted")
    assert decision.old_creator == "Someone"
    assert decision.reporter_ids == [reporter.id]
    assert "Bad" in staff_client.get(URL).content.decode()  # in Recent decisions


def test_deciding_on_a_skin_that_is_gone_says_so(staff_client):
    skin = SkinFactory()
    skin_id = skin.id
    skin.delete()

    response = staff_client.post(
        f"/moderation/skins/{skin_id}/decide/", {"action": "dismiss"}, follow=True
    )

    assert "already gone" in response.content.decode()


def test_unknown_action_is_404(staff_client):
    assert _decide(staff_client, SkinFactory(), "ban").status_code == 404


def test_decide_is_post_only(staff_client):
    skin = SkinFactory()

    assert staff_client.get(f"/moderation/skins/{skin.id}/decide/").status_code == 405


def test_change_creator_service_validates_bonk_names():
    skin = SkinFactory()

    with pytest.raises(ValidationError):
        moderation.change_creator(skin.id, "x" * 200, by=None)
