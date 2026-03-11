from __future__ import annotations

import threading

from sqlalchemy import text as sa_text

from .db import engine, _table_exists

CONCEPT_MEASURE_LABELS: dict[str, str] = {
    "bedtime_consistency": "nights/week",
    "cardio_frequency": "days/week",
    "emotional_regulation": "days/week",
    "flexibility_mobility": "days/week",
    "fruit_veg": "portions/day",
    "hydration": "litres/day",
    "optimism_perspective": "days/week",
    "positive_connection": "days/week",
    "processed_food": "portions/day",
    "protein_intake": "portions/day",
    "sleep_duration": "nights/week",
    "sleep_quality": "mornings/week",
    "strength_training": "sessions/week",
    "stress_recovery": "days/week",
    "support_openness": "days/week",
}

_CONCEPT_METADATA_READY = False
_CONCEPT_METADATA_LOCK = threading.Lock()


def ensure_concept_measure_labels() -> None:
    global _CONCEPT_METADATA_READY
    if _CONCEPT_METADATA_READY:
        return
    with _CONCEPT_METADATA_LOCK:
        if _CONCEPT_METADATA_READY:
            return

        try:
            from .models import Concept  # local import avoids cycles

            Concept.__table__.create(bind=engine, checkfirst=True)
        except Exception as e:
            print(f"[concepts] ensure table failed: {e}")

        with engine.begin() as conn:
            if not _table_exists(conn, "concepts"):
                _CONCEPT_METADATA_READY = True
                return

            for code, description in CONCEPT_MEASURE_LABELS.items():
                try:
                    conn.execute(
                        sa_text(
                            """
                            UPDATE concepts
                            SET description = :description
                            WHERE code = :code
                              AND (description IS NULL OR description = '');
                            """
                        ),
                        {"code": code, "description": description},
                    )
                except Exception:
                    pass

        _CONCEPT_METADATA_READY = True
