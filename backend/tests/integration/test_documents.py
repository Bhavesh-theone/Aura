"""Documents: versions, executed flag, class confirmation, and access logging (F5)."""
import hashlib

import pytest
from sqlalchemy import text

from tests.integration.helpers import make_deal, upload

PAYLOAD_KEYS = {"id", "deal_id", "doc_class", "filename", "sha256", "byte_size",
                "current_version", "contains_upsi", "sensitivity", "is_executed",
                "class_confirmed", "uploaded_by", "uploaded_at"}


def _scalar(api, sql, **params):
    return api.session.execute(text(sql), params).scalar()


def test_document_payload_is_exactly_the_contract(api):
    deal = make_deal(api)
    doc = upload(api, deal, "a.pdf", "nda", b"one")
    assert set(doc) == PAYLOAD_KEYS
    assert doc["current_version"] == 1 and doc["is_executed"] is False
    assert api.call("GET", f"/api/documents/{doc['id']}").json() == doc
    assert api.call("GET", f"/api/deals/{deal}/documents").json() == [doc]


def test_same_filename_on_the_same_deal_adds_a_version_row_and_bumps_the_document(api):
    deal = make_deal(api)
    first = upload(api, deal, "spa.pdf", "spa", b"draft one")
    second = upload(api, deal, "spa.pdf", "spa", b"draft two longer")
    assert second["id"] == first["id"] and second["current_version"] == 2
    assert second["sha256"] == hashlib.sha256(b"draft two longer").hexdigest()
    assert second["byte_size"] == len(b"draft two longer")
    assert _scalar(api, "SELECT COUNT(*) FROM document") == 1

    versions = api.call("GET", f"/api/documents/{first['id']}/versions").json()
    assert [v["version"] for v in versions] == [1, 2]
    assert versions[0]["sha256"] == hashlib.sha256(b"draft one").hexdigest()
    assert versions[1]["sha256"] == second["sha256"]
    assert set(versions[0]) == {"version", "sha256", "byte_size", "uploaded_by", "uploaded_at"}
    assert versions[0]["uploaded_by"] == "bhavesh"
    assert _scalar(api, "SELECT COUNT(*) FROM doc_version WHERE document_id = :d",
                   d=first["id"]) == 2
    # both versions are kept in the file store
    assert api.store.read_head(first["sha256"]) == "draft one"

    other = upload(api, deal, "other.pdf", "spa", b"x")  # a different name is a new document
    assert other["id"] != first["id"] and other["current_version"] == 1
    other_deal = make_deal(api, "H-2")  # the same name on another deal is too
    assert upload(api, other_deal, "spa.pdf", "spa")["id"] not in (first["id"], other["id"])


def test_a_new_version_is_not_executed_until_someone_says_so_again(api):
    deal = make_deal(api)
    doc = upload(api, deal, "el.pdf", "engagement_letter", b"v1")
    api.call("PATCH", f"/api/documents/{doc['id']}", json={"is_executed": True})
    assert api.call("GET", f"/api/documents/{doc['id']}").json()["is_executed"] is True
    again = upload(api, deal, "el.pdf", "engagement_letter", b"v2")
    assert again["is_executed"] is False and again["current_version"] == 2


def test_metadata_view_and_download_are_logged_but_listing_is_not(api):
    deal = make_deal(api)
    doc = upload(api, deal, "a.pdf", "nda")
    api.call("GET", f"/api/deals/{deal}/documents")
    api.call("GET", f"/api/documents/{doc['id']}/versions")
    assert _scalar(api, "SELECT COUNT(*) FROM doc_access_log") == 0

    api.call("GET", f"/api/documents/{doc['id']}")
    api.call("GET", f"/api/documents/{doc['id']}/download")
    rows = api.session.execute(text("SELECT document_id, accessed_by, action FROM "
                                    "doc_access_log ORDER BY id")).all()
    assert [tuple(r) for r in rows] == [(doc["id"], "bhavesh", "view"),
                                        (doc["id"], "bhavesh", "download")]
    actions = api.session.execute(text("SELECT action FROM audit_entries WHERE action LIKE "
                                       "'document_%' ORDER BY id")).scalars().all()
    assert actions == ["document_uploaded", "document_viewed", "document_downloaded"]


def test_patch_sets_executed_and_class_and_a_chosen_class_is_confirmed(api):
    deal = make_deal(api)
    doc = upload(api, deal, "a.pdf", "nda")
    assert doc["class_confirmed"] is False
    r = api.call("PATCH", f"/api/documents/{doc['id']}",
                 json={"doc_class": "term_sheet", "is_executed": True})
    assert r.status_code == 200
    body = r.json()
    assert body["doc_class"] == "term_sheet" and body["class_confirmed"] is True
    assert body["is_executed"] is True and set(body) == PAYLOAD_KEYS
    only_flag = api.call("PATCH", f"/api/documents/{doc['id']}", json={"is_executed": False})
    assert only_flag.json()["doc_class"] == "term_sheet"
    assert only_flag.json()["class_confirmed"] is True and only_flag.json()["is_executed"] is False
    assert api.call("PATCH", f"/api/documents/{doc['id']}",
                    json={"doc_class": "teaser"}).status_code == 422
    audit = api.session.execute(text("SELECT payload FROM audit_entries WHERE action = "
                                     "'document_updated' ORDER BY id")).scalars().all()
    assert len(audit) == 2
    assert audit[0]["doc_class"] == "term_sheet" and audit[0]["is_executed"] is True


def test_class_confirmed_by_patch_stays_when_only_the_flag_changes_later(api):
    deal = make_deal(api)
    doc = upload(api, deal, "a.pdf", "nda")
    api.call("PATCH", f"/api/documents/{doc['id']}", json={"is_executed": True})
    assert api.call("GET", f"/api/documents/{doc['id']}").json()["class_confirmed"] is False


@pytest.mark.parametrize("user, status", [("asha", 404), ("priya", 403), ("admin", 403)])
def test_patch_needs_the_role_and_the_wall(api, user, status):
    deal = make_deal(api)
    doc = upload(api, deal, "a.pdf", "nda")
    r = api.call("PATCH", f"/api/documents/{doc['id']}", user=user,
                 json={"is_executed": True})
    assert r.status_code == status  # asha is an analyst but not on the wall: 404 as ever


def test_view_and_versions_are_walled(api):
    deal = make_deal(api)
    doc = upload(api, deal, "a.pdf", "nda")
    for url in (f"/api/documents/{doc['id']}", f"/api/documents/{doc['id']}/versions"):
        assert api.call("GET", url, user="asha").status_code == 404
    assert _scalar(api, "SELECT COUNT(*) FROM doc_access_log") == 0
    assert api.call("GET", "/api/documents/999").status_code == 404


def test_doc_version_primary_key_is_document_and_version(api):
    deal = make_deal(api)
    doc = upload(api, deal, "a.pdf", "nda")
    with pytest.raises(Exception, match="duplicate key|unique"):
        api.session.execute(text(
            "INSERT INTO doc_version (document_id, version, sha256, byte_size, uploaded_by, "
            "uploaded_at) VALUES (:d, 1, 'x', 1, 'u', '2026-01-01')"), {"d": doc["id"]})
    api.session.rollback()