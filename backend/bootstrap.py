from pathlib import Path
import shutil
from sqlalchemy import select

from app.seed_customer_demo import run_seed as seed_customer
from app.config import get_settings as get_customer_settings
from app.auth import hash_password as customer_hash
from app.database import SessionLocal as CustomerSession
from app.models import Project as CustomerProject, User as CustomerUser
from app.services.validation_layer import import_validation_folder
from app.services.benchmark_import import import_folder as import_benchmark_folder

from discovery_engine.config import get_settings as get_engine_settings
from discovery_engine.auth import hash_password as engine_hash
from discovery_engine.database import (
    Base as EngineBase,
    SessionLocal as EngineSession,
    engine as engine_sql,
    ensure_schema as ensure_engine_schema,
)
from discovery_engine.models import User as EngineUser

ROOT = Path(__file__).resolve().parent


def bootstrap():
    customer_settings = get_customer_settings()
    seed_customer()
    with CustomerSession() as db:
        # Passwords are reapplied on every boot so rotating an environment
        # variable takes effect on the next deploy.
        for email, password in (
            (customer_settings.demo_admin_email, customer_settings.demo_admin_password),
            (customer_settings.demo_manager_email, customer_settings.manager_password),
            (customer_settings.demo_analyst_email, customer_settings.analyst_password),
        ):
            user = db.scalar(select(CustomerUser).where(CustomerUser.email == email.lower()))
            if user:
                user.password_hash = customer_hash(password)
        db.commit()
        for user in db.scalars(select(CustomerUser).order_by(CustomerUser.id)):
            print(f"User ready: {user.email} ({user.role.value})")
        project = db.scalar(select(CustomerProject).order_by(CustomerProject.id))
        if project:
            loaded_validation = import_validation_folder(db, project.id)
            for result in loaded_validation:
                superseded = (
                    f" (replaces {', '.join(result['superseded'])})" if result.get("superseded") else ""
                )
                print(
                    f"Validation layer for {result['city']} from {result['workbook']}{superseded}: "
                    f"{result['added']} new, {result['refreshed']} refreshed."
                )
            if not loaded_validation:
                print("Validation layer: no workbook found in backend/misseddata.")
            for loaded in import_benchmark_folder(db, project.id):
                print(
                    f"Benchmark city {loaded['city']} from {loaded['workbook']}: "
                    f"{loaded['added']} new, {loaded['refreshed']} refreshed, "
                    f"{loaded['matched_pairs']} matched and {loaded['possible_pairs']} possible pairs."
                )

    engine_settings = get_engine_settings()
    # The bundled seed is a SQLite file, so it is only copied for a SQLite
    # deployment. On Postgres the engine schema is created empty instead.
    ensure_engine_schema()
    seed_db = ROOT / "discovery_engine_seed.db"
    engine_db = None
    if engine_settings.engine_database_url.startswith("sqlite:///"):
        raw_path = engine_settings.engine_database_url.removeprefix("sqlite:///")
        engine_db = Path(raw_path)
        if not engine_db.is_absolute():
            engine_db = ROOT / engine_db
        engine_db.parent.mkdir(parents=True, exist_ok=True)
        if not engine_db.exists() and seed_db.exists():
            shutil.copy2(seed_db, engine_db)
    EngineBase.metadata.create_all(bind=engine_sql)
    with EngineSession() as db:
        users = list(db.scalars(select(EngineUser)).all())
        user = users[0] if users else None
        if user is None:
            user = EngineUser(
                email=engine_settings.demo_admin_email.lower(),
                full_name="JSAN GeoDiscover Administrator",
                password_hash=engine_hash(engine_settings.demo_admin_password),
            )
            db.add(user)
        else:
            user.email = engine_settings.demo_admin_email.lower()
            user.password_hash = engine_hash(engine_settings.demo_admin_password)
            user.is_active = True
        db.commit()
    print("Integrated GeoDiscover databases are ready.")


if __name__ == "__main__":
    bootstrap()
