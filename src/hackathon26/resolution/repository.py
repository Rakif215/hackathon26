"""Read-only canonical Exasol medication/appearance access."""

from collections.abc import Callable
from datetime import date
from typing import Protocol

from pyexasol import ExaConnection, ExaError
from pydantic import ValidationError

from hackathon26.db import connect

from .models import RecordedMedication


class UnknownPatient(Exception):
    """No matching synthetic patient in the canonical data store."""


class MedicationStoreUnavailable(Exception):
    """Data unavailable or incompatible; never interpreted as an empty med list."""


class MedicationRepository(Protocol):
    def current_medications(self, patient_id: int, as_of: date) -> list[RecordedMedication]: ...


_CURRENT_MEDICATIONS = """
SELECT pm.PATIENT_MED_ID, d.DRUG_ID, d.GENERIC_NAME, pm.STRENGTH,
       a.COLOR, a.SHAPE, a.IMPRINT, a.STRENGTH, a.MANUFACTURER, a.SRC_NAME
FROM MEDGUARD.PATIENT_MEDICATION pm
LEFT JOIN MEDGUARD.DRUG d ON d.DRUG_ID = pm.DRUG_ID
LEFT JOIN MEDGUARD.DRUG_APPEARANCE a ON a.DRUG_ID = d.DRUG_ID
WHERE pm.PATIENT_ID = {patient_id}
  AND pm.STARTED_ON IS NOT NULL AND pm.STARTED_ON <= TO_DATE({as_of}, 'YYYY-MM-DD')
  AND (pm.STOPPED_ON IS NULL OR pm.STOPPED_ON > TO_DATE({as_of}, 'YYYY-MM-DD'))
ORDER BY pm.PATIENT_MED_ID, a.MANUFACTURER, a.COLOR, a.SHAPE
"""


class ExasolMedicationRepository:
    def __init__(self, connection_factory: Callable[[], ExaConnection] = connect):
        self._connect = connection_factory

    def current_medications(self, patient_id: int, as_of: date) -> list[RecordedMedication]:
        try:
            with self._connect() as conn:
                patients = conn.execute(
                    "SELECT PATIENT_ID FROM MEDGUARD.PATIENT WHERE PATIENT_ID = {patient_id} AND IS_SYNTHETIC = TRUE",
                    {"patient_id": patient_id},
                ).fetchall()
                if not patients:
                    raise UnknownPatient("Synthetic patient not found")
                rows = conn.execute(_CURRENT_MEDICATIONS, {
                    "patient_id": patient_id, "as_of": as_of.isoformat(),
                }).fetchall()
            return [RecordedMedication(**dict(zip(RecordedMedication.model_fields, row, strict=True))) for row in rows]
        except (ExaError, OSError, RuntimeError, ValueError, ValidationError) as error:
            raise MedicationStoreUnavailable("Medication data unavailable or incompatible") from error
