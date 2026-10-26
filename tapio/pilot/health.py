"""Local database availability and startup preflight; never calls a model."""

from sqlalchemy import text

from tapio.pilot.config import load_config, readonly_engine, readonly_session, source_fingerprints

DATABASE_HELP = (
    "The local database is offline or cannot be reached. "
    "Start TAPIO with ./scripts/start_pilot.sh, then retry."
)


def database_available():
    engine = readonly_engine()
    try:
        with readonly_session(engine) as session:
            session.execute(text("SELECT 1"))
    finally:
        engine.dispose()


def preflight():
    stage = "CONFIGURATION"
    try:
        config, _ = load_config()
        stage = "SOURCE_PREFLIGHT"
        engine = readonly_engine()
        try:
            source_fingerprints(engine, config)
        finally:
            engine.dispose()
    except Exception:
        print("Pilot startup stopped: " + stage + " failed.")
        return 1
    print("Pilot configuration and source fingerprints verified. No model calls made.")
    return 0


if __name__ == "__main__":
    raise SystemExit(preflight())
