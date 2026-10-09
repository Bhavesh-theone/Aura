import pytest
from sqlalchemy.orm import sessionmaker

from aura.api.security import hash_password
from aura.core.domain.enums import Role, TransactionClass
from aura.core.services.create_deal import create_deal
from aura.data.models.tables import UserRow
from aura.data.repositories.sql import SqlAuditRepository
from aura.data.repositories.sql_deals import (SqlDealRepository, SqlStageHistoryRepository,
                                              SqlWallRepository)
from aura.data.walls import SYSTEM
from aura.mcp.identity import acting_as
from aura.mcp.servers import deals_server
from aura.mcp.servers.deals_server import add_internal_note, get_deal_status, list_deals
from tests.integration.pgtest import fresh_engine


@pytest.fixture(autouse=True)
def db(monkeypatch):
    engine = fresh_engine()
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as s:
        for name in ("bhavesh", "asha"):
            s.add(UserRow(username=name, password_hash=hash_password("x"), role="dealmaker"))
        s.commit()
        for ext, name, cls in [("D-001", "Sunrise Infra", TransactionClass.DEBT),
                               ("D-002", "Ravi Menon Ventures", TransactionClass.ALLIANCE)]:
            create_deal(ext, name, cls, "bhavesh", Role.DEALMAKER, SqlDealRepository(s, SYSTEM),
                        SqlStageHistoryRepository(s, SYSTEM), SqlAuditRepository(s, SYSTEM),
                        SqlWallRepository(s, SYSTEM))
        s.commit()
    monkeypatch.setattr(deals_server, "SessionLocal", factory)


@pytest.fixture(autouse=True)
def as_bhavesh():
    with acting_as("bhavesh"):
        yield


def test_get_deal_status_reads_the_database():
    result = get_deal_status("D-001")
    assert "Sunrise" in result and "ORIGINATED" in result


def test_get_deal_status_handles_unknown_deal():
    assert "No deal" in get_deal_status("D-999")


def test_list_deals_returns_all():
    result = list_deals()
    assert "D-001" in result and "D-002" in result


def test_add_internal_note_confirms():
    assert "D-001" in add_internal_note("D-001", "spoke to founder")


def test_a_non_member_sees_nothing_through_any_tool():
    with acting_as("asha"):
        assert "No deal found" in get_deal_status("D-001")
        assert list_deals() == ""
        assert "No deal found" in add_internal_note("D-001", "sneaky note")


def test_with_no_acting_user_nothing_is_visible(monkeypatch):
    monkeypatch.delenv("AURA_MCP_USER", raising=False)
    with acting_as(None):
        assert "No deal found" in get_deal_status("D-001")
        assert list_deals() == ""


def test_standalone_server_takes_its_user_from_the_environment(monkeypatch):
    monkeypatch.setenv("AURA_MCP_USER", "bhavesh")
    with acting_as(None):
        assert "Sunrise" in get_deal_status("D-001")
