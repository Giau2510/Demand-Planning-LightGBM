"""1.4.0 SEL2 pipeline errors: AppError codes (bilingual texts in app/messages.py). The pure modules (scope, simple,
lgbm, select) raise ValueError / RuntimeError; the pipeline maps them to a code with mapped()."""
from __future__ import annotations

from contextlib import contextmanager

from ...messages import AppError

DISABLED = "SEL2_DISABLED"                      # sel2_pipeline.enabled = False (emergency switch): nothing runs
OPEN_HOURS_INVALID = "OPEN_HOURS_INVALID"        # open hours missing before D-lag, or not filled within the lag
WINDOW_NOT_COVERED = "SEL2_WINDOW_NOT_COVERED"   # the data does not cover a window of a rule (scope 90 d, DOW4 84 d ...)
NO_MODEL = "SEL2_NO_MODEL"                       # no trained LightGBM candidate of the week nor of the week before
EMPTY_SCOPE = "SEL2_EMPTY_SCOPE"                 # no series in scope of the day
MISSING_FORECAST = "SEL2_MISSING_FORECAST"       # a candidate forecast of the day is missing
HISTORY_INVALID = "SEL2_HISTORY_INVALID"         # stored candidate history / actuals inconsistent (duplicates)
MODEL_FILE_MISMATCH = "SEL2_MODEL_FILE_MISMATCH"  # a model file is missing or its sha256 differs from the record
LOW_MEMORY = "SEL2_LOW_MEMORY"                   # free commit below the training minimum (retryable)
TRAIN_FAILED = "SEL2_TRAIN_FAILED"
ORIGIN_INVALID = "SEL2_ORIGIN_INVALID"           # a training origin that is not the retraining weekday
SCOPE_CONFLICT = "SEL2_SCOPE_CONFLICT"           # the day already has candidate runs of another data scope
CONFIRM_REQUIRED = "SEL2_CONFIRM_REQUIRED"       # CLI write command without --yes

RETRYABLE = {LOW_MEMORY}


class Sel2Error(AppError):
    """AppError of the SEL2 pipeline; retryable = the same call may succeed later without any change (memory)."""

    def __init__(self, code: str, detail: str | None = None, status: int = 409, **params):
        super().__init__(code, status=status, detail=detail, **params)
        self.retryable = code in RETRYABLE


@contextmanager
def mapped(code: str):
    """A ValueError / RuntimeError of a pure module -> Sel2Error(code) (OPEN_HOURS_INVALID and a missing chosen forecast
    keep their own code); AppError and every other exception (Cancelled, MemoryError ...) pass unchanged."""
    try:
        yield
    except AppError:
        raise
    except (ValueError, RuntimeError) as e:
        if type(e) not in (ValueError, RuntimeError):
            raise
        text = str(e)
        c = (OPEN_HOURS_INVALID if "OPEN_HOURS_INVALID" in text else
             MISSING_FORECAST if "without a forecast" in text else
             WINDOW_NOT_COVERED if "not covered" in text else code)
        raise Sel2Error(c, detail=text[:500]) from e
