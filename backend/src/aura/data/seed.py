from sqlalchemy import select
from sqlalchemy.orm import Session

from aura.api.security import hash_password
from aura.data.engine import Base, SessionLocal, engine
from aura.data.models.tables import DealRow, UserRow


def seed() -> None:
    Base.metadata.create_all(engine)
    with SessionLocal() as s:  # type: Session
        if s.scalars(select(UserRow).where(UserRow.username == "bhavesh")).first() is None:
            s.add(UserRow(username="bhavesh", password_hash=hash_password("admin123"),
                          role="admin"))
        if s.scalars(select(DealRow)).first() is None:
            s.add_all([
                DealRow(external_id="D-001", name="Sunrise Infra",
                        stage="NDA signed", owner="bhavesh"),
                DealRow(external_id="D-002", name="Ravi Menon Ventures",
                        stage="Sourced", owner="bhavesh"),
            ])
        s.commit()
