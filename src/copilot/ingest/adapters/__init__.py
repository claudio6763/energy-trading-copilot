"""Adapters de fonte. Um contrato, varias origens."""

from copilot.ingest.adapters.base import BaseAdapter, UnavailableAdapter
from copilot.ingest.adapters.demo import DemoDataAdapter
from copilot.ingest.adapters.licensed import B3N5xAdapter, BbceForwardAdapter
from copilot.ingest.adapters.public import (
    AnaAdapter,
    AneelAdapter,
    CceeAdapter,
    ClimateAdapter,
    EnsoOniAdapter,
    EpeAdapter,
    OnsAdapter,
    classify_enso,
)
from copilot.ingest.adapters.uploads import (
    ForwardCurveUploadAdapter,
    LicensedCurveCsvAdapter,
    ManualObservationAdapter,
    looks_like_spot,
)

__all__ = [
    "AnaAdapter",
    "AneelAdapter",
    "B3N5xAdapter",
    "BaseAdapter",
    "BbceForwardAdapter",
    "CceeAdapter",
    "ClimateAdapter",
    "DemoDataAdapter",
    "EnsoOniAdapter",
    "EpeAdapter",
    "ForwardCurveUploadAdapter",
    "LicensedCurveCsvAdapter",
    "ManualObservationAdapter",
    "OnsAdapter",
    "UnavailableAdapter",
    "classify_enso",
    "looks_like_spot",
]
