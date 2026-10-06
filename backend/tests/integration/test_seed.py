import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from aura.config import get_settings
from aura.data import seed as seed_module
from aura.data.engine import make_engine
from aura.data.verify_audit import verify_chain


@pytest.fixture()
def scratch(tmp_path, monkeypatch):
    url = f"sqlite:///{(tmp_path / 'seed.db').as_posix()}"
    monkeypatch.setenv("AURA_DATABASE_URL", url)
    get_settings.cache_clear()
    engine = make_engine(url)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(seed_module, "engine", engine)
    monkeypatch.setattr(seed_module, "SessionLocal", factory)
    yield factory
    get_settings.cache_clear()


def test_seed_is_idempotent_and_leaves_a_verifiable_chain(scratch):
    seed_module.seed()
    seed_module.seed()
    with scratch() as s:
        assert s.execute(text("SELECT username FROM users ORDER BY id")).scalars().all() == [
            "bhavesh", "asha", "priya", "admin"]
        assert s.execute(text("SELECT username, role FROM users ORDER BY id")).all() == [
            ("bhavesh", "dealmaker"), ("asha", "analyst"), ("priya", "compliance"),
            ("admin", "admin")]
        assert s.execute(text("SELECT external_id FROM deals ORDER BY id")).scalars().all() == [
            "D-001", "D-002"]
        assert s.execute(text("SELECT COUNT(*) FROM stage_guard")).scalar() == 12
        # one guard set per forward move, none of them left without a description
        moves = s.execute(text("SELECT DISTINCT from_stage, to_stage FROM stage_guard")).all()
        assert len(moves) == 11
        assert s.execute(text("SELECT COUNT(*) FROM stage_guard WHERE override_role IS NULL "
                              "OR severity != 'blocking'")).scalar() == 0
        assert s.execute(text("SELECT guard_name FROM stage_guard WHERE override_role = "
                              "'compliance' ORDER BY id")).scalars().all() == [
            "T9_no_open_blockers", "T9_compliance_signoff", "T11_all_cps_cleared"]
        assert s.execute(text("SELECT COUNT(*) FROM stage_guard WHERE description = ''")
                         ).scalar() == 0
        assert s.execute(text("SELECT COUNT(*) FROM checklist_item_template")).scalar() == 8
        assert s.execute(text("SELECT layer, transaction_class FROM checklist_template "
                              "ORDER BY id")).all() == [("base", None), ("subclass", "DEBT"),
                                                        ("subclass", "ALLIANCE")]
        assert s.execute(text("SELECT COUNT(*) FROM checklist_item_template WHERE "
                              "template_id IS NULL")).scalar() == 0
        assert verify_chain(s) is None


def test_the_three_working_users_are_on_every_seeded_wall_and_admin_is_not(scratch):
    seed_module.seed()
    seed_module.seed()
    with scratch() as s:
        rows = s.execute(text(
            "SELECT d.external_id, u.username FROM deals d JOIN wall w ON w.deal_id = d.id "
            "JOIN wall_member m ON m.wall_id = w.id JOIN users u ON u.id = m.user_id "
            "WHERE m.removed_at IS NULL ORDER BY d.id, u.id")).all()
        assert [tuple(r) for r in rows] == [
            ("D-001", "bhavesh"), ("D-001", "asha"), ("D-001", "priya"),
            ("D-002", "bhavesh"), ("D-002", "asha"), ("D-002", "priya")]


def test_a_member_removed_on_purpose_is_not_added_back_by_reseeding(scratch):
    seed_module.seed()
    with scratch() as s:
        s.execute(text("UPDATE wall_member SET removed_at = CURRENT_TIMESTAMP WHERE user_id = "
                       "(SELECT id FROM users WHERE username = 'asha')"))
        s.commit()
    seed_module.seed()
    with scratch() as s:
        assert s.execute(text(
            "SELECT COUNT(*) FROM wall_member m JOIN users u ON u.id = m.user_id "
            "WHERE u.username = 'asha' AND m.removed_at IS NULL")).scalar() == 0
