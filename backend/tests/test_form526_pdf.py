"""WAVE7 B — real fillable 21-526EZ PDF. Fills the OFFICIAL AcroForm and reads the
values back with pypdf. Asserts the high-confidence fields land and that the fields
we deliberately never touch (SSN, DOB, address) stay blank. Same SQLite harness as
test_form526.py.
"""

from __future__ import annotations

import io
import uuid
from contextlib import asynccontextmanager
from datetime import date

import pytest

fastapi = pytest.importorskip("fastapi")
pytest.importorskip("aiosqlite")
pytest.importorskip("pypdf")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from pypdf import PdfReader  # noqa: E402
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.ext.compiler import compiles  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402
from sqlalchemy.schema import ColumnDefault  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from app import deps, models  # noqa: E402
from app.db import Base  # noqa: E402
from app.pdf import form526_fill  # noqa: E402
from app.routers import form526 as form526_mod  # noqa: E402

try:
    from pgvector.sqlalchemy import Vector  # noqa: E402
except Exception:  # pragma: no cover
    Vector = None


@compiles(PGUUID, "sqlite")
def _pg_uuid_sqlite(type_, compiler, **kw):  # noqa: ANN001, ANN003
    return "CHAR(36)"


@compiles(JSONB, "sqlite")
def _jsonb_sqlite(type_, compiler, **kw):  # noqa: ANN001, ANN003
    return "JSON"


if Vector is not None:
    @compiles(Vector, "sqlite")
    def _vector_sqlite(type_, compiler, **kw):  # noqa: ANN001, ANN003
        return "TEXT"


_TABLES = [
    models.User.__table__,
    models.VeteranProfile.__table__,
    models.ClaimedCondition.__table__,
    models.EvidenceItem.__table__,
    models.ItfRecord.__table__,
]
for _t in _TABLES:
    for _c in _t.columns:
        if _c.server_default is not None and "gen_random_uuid" in str(
            getattr(_c.server_default, "arg", "")
        ):
            _c.server_default = None
            _c.default = ColumnDefault(lambda: uuid.uuid4())

USER_A = uuid.UUID("00000000-0000-0000-0000-0000000000a1")
COND_PTSD = uuid.UUID("00000000-0000-0000-0000-000000000011")
COND_KNEE = uuid.UUID("00000000-0000-0000-0000-000000000012")


@pytest.fixture()
def env(tmp_path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'pdf.db'}", poolclass=NullPool
    )
    Session = async_sessionmaker(engine, expire_on_commit=False)
    current = {"uid": str(USER_A)}

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all, tables=_TABLES)
        async with Session() as s:
            s.add_all([
                models.User(id=USER_A, email="jane@example.com",
                            password_hash="x", full_name="Riley Example"),
                models.VeteranProfile(
                    user_id=USER_A,
                    service_periods=[
                        {"branch": "Army", "component": "Active",
                         "start_date": "2004-01-15", "end_date": "2008-06-30",
                         "discharge_character": "Honorable"},
                    ],
                    combat_service=True,
                ),
                models.ClaimedCondition(
                    id=COND_PTSD, user_id=USER_A, name="Tinnitus", claim_type="direct",
                    onset_date=date(2007, 5, 1), in_service_event="Artillery exposure",
                ),
                models.ClaimedCondition(
                    id=COND_KNEE, user_id=USER_A, name="Right knee strain",
                    claim_type="direct",
                ),
            ])
            await s.commit()
        yield
        await engine.dispose()

    app = FastAPI(lifespan=lifespan)
    app.include_router(form526_mod.router, prefix="/api")

    async def _test_db():
        async with Session() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[deps.current_user_id] = lambda: current["uid"]
    app.dependency_overrides[deps.get_db] = _test_db
    with TestClient(app) as client:
        yield SimpleNamespace(client=client, current=current)


def _fields(pdf_bytes: bytes) -> dict:
    return PdfReader(io.BytesIO(pdf_bytes)).get_fields() or {}


def _v(fields: dict, name: str):
    f = fields.get(name)
    return None if f is None else f.get("/V")


def test_pdf_fills_high_confidence_fields(env):
    resp = env.client.get("/api/form526/pdf")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert "attachment" in resp.headers["content-disposition"]
    assert "DRAFT" in resp.headers["content-disposition"] or "review-and-sign" in resp.headers["content-disposition"]

    pdf = resp.content
    assert pdf[:4] == b"%PDF"
    f = _fields(pdf)

    P = form526_fill._PAGE
    D = form526_fill._DIS
    # Identity split from "Riley Example".
    assert _v(f, P + "Veteran_Service_Member_First_Name[0]") == "Jane"
    assert _v(f, P + "Veteran_Service_Member_Last_Name[0]") == "Veteran"
    assert _v(f, P + "Veteran_Service_Member_Middle_Initial[0]") == "Q"
    assert _v(f, P + "Email_Address_Optional[0]") == "jane@example.com"
    # Service dates from the first period.
    assert _v(f, P + "Beginning_Date_Year[0]") == "2004"
    assert _v(f, P + "Ending_Date_Year[0]") == "2008"
    # Standard claim process checked.
    assert str(_v(f, P + "Standard_Claim_Process[0]")) in ("/1", "1")
    # Both conditions, in order, land in the disabilities table.
    assert _v(f, D + "CURRENTDISABILITY[0]") == "Tinnitus"
    assert _v(f, D + "CURRENTDISABILITY[1]") == "Right knee strain"
    assert _v(f, D + "ExplainHowDisabilityRelatesToEvent_Exposure_Injury[0]") == "Artillery exposure"


def test_pdf_blank_when_no_saved_identity(env):
    # With NO identity saved on the profile, nothing sensitive is filled (the
    # veteran completes it). SSN is NEVER filled regardless (see the pure test).
    f = _fields(env.client.get("/api/form526/pdf").content)
    P = form526_fill._PAGE
    for name in [
        "SocialSecurityNumber_FirstThreeNumbers[0]",
        "SocialSecurityNumber_LastFourNumbers[0]",
        "VA_File_Number[0]",
        "Date_Of_Birth_Year[0]",
        "CurrentMailingAddress_City[0]",
        "CurrentMailingAddress_NumberAndStreet[0]",
    ]:
        assert not _v(f, P + name), f"{name} must stay blank"


def test_identity_fills_contact_but_never_ssn_or_signature():
    """LEGAL LANE: given a full identity, we fill address/DOB/phone (and the opt-in
    VA file number on the veteran's own draft) — but the SSN and signature fields are
    NEVER in the output map. This is the guarantee the whole feature rests on."""
    P = form526_fill._PAGE
    vals = form526_fill.build_field_values(
        full_name="Casey Example",
        email="j@x.com",
        service_periods=[],
        contentions=[],
        identity={
            "date_of_birth": "1980-04-05",
            "phone": "(843) 555-1234",
            "address": {"street": "123 Example St", "city": "Springfield", "state": "SC", "zip": "294010000"},
            "va_file_number": "C12345678",
        },
        is_own_draft=True,
    )
    # Contact/identity IS filled.
    assert vals[P + "CurrentMailingAddress_City[0]"] == "Springfield"
    assert vals[P + "CurrentMailingAddress_ZIPOrPostalCode_FirstFiveNumbers[0]"] == "29439"
    assert vals[P + "CurrentMailingAddress_ZIPOrPostalCode_LastFourNumbers[0]"] == "0123"
    assert vals[P + "Date_Of_Birth_Year[0]"] == "1980"
    assert vals[P + "Daytime_Phone_Number_Area_Code[0]"] == "843"
    assert vals[P + "VA_File_Number[0]"] == "C12345678"
    # SSN + signature are NEVER emitted, even with a full identity present.
    for name in list(vals):
        assert "SocialSecurity" not in name, f"{name} must never be filled"
        assert "Signature" not in name and "Date_Signed" not in name, f"{name} must never be filled"

    # The VA file number is withheld when it is NOT the veteran's own draft.
    not_own = form526_fill.build_field_values(
        full_name="Casey Example", email="", service_periods=[], contentions=[],
        identity={"va_file_number": "C12345678"}, is_own_draft=False,
    )
    assert (P + "VA_File_Number[0]") not in not_own


def test_build_field_values_pure():
    # Single-token name → first only, last blank (form still gets something).
    vals = form526_fill.build_field_values(
        full_name="Sam", email="", service_periods=None, contentions=[],
    )
    P = form526_fill._PAGE
    assert vals[P + "Veteran_Service_Member_First_Name[0]"] == "Sam"
    assert (P + "Veteran_Service_Member_Last_Name[0]") not in vals
    # Empty email is not emitted (pypdf leaves it blank).
    assert (P + "Email_Address_Optional[0]") not in vals
    # More than 15 conditions are capped at the form's 15 rows.
    many = form526_fill.build_field_values(
        full_name="A B", email="a@b.co", service_periods=[],
        contentions=[{"name": f"C{i}"} for i in range(20)],
    )
    D = form526_fill._DIS
    assert (D + "CURRENTDISABILITY[14]") in many
    assert (D + "CURRENTDISABILITY[15]") not in many


def test_every_form_fills_identity_but_never_ssn_or_signature():
    """LEGAL LANE across the WHOLE form set: given a full identity + dependents,
    no filler ever emits an SSN or signature/date-signed field. Enforced by the
    shared identity_fill helper (SSN is not a valid field key anywhere)."""
    from app.pdf.registry import REGISTRY

    identity = {
        "date_of_birth": "1980-04-05",
        "phone": "843-555-1234",
        "address": {"street": "123 Example St", "city": "Springfield", "state": "SC", "zip": "294010000"},
        "va_file_number": "C12345678",
    }
    dependents = [{
        "relationship": "spouse", "full_name": "Jordan Example",
        "date_of_birth": "1982-06-07", "marriage_date": "2010-06-01",
        "marriage_location": "Charleston SC",
    }]
    for form_id, spec in REGISTRY.items():
        vals = spec.build_field_values(
            full_name="Casey Example", email="j@x.com", service_periods=[],
            contentions=[], identity=identity, dependents=dependents, is_own_draft=True,
        )
        for name in vals:
            low = name.lower()
            assert "socialsecurity" not in low, f"{form_id}: {name} is an SSN field"
            assert "signature" not in low and "date_signed" not in low, f"{form_id}: {name}"
    # 686c pre-fills the spouse.
    c686 = REGISTRY["21-686c"].build_field_values(
        full_name="Casey Example", email="", service_periods=[], contentions=[],
        identity=identity, dependents=dependents, is_own_draft=True,
    )
    assert any("SPOUSE" in k for k in c686), "21-686c must pre-fill the spouse block"
