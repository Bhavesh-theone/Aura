"""Agent adapters.

Importing this package sets the telemetry kill switches BEFORE any CrewAI
module is imported. The values in backend/.env are only read by
pydantic-settings into the Settings object; they never reach os.environ, so
relying on .env alone would leave CrewAI/OpenTelemetry at their defaults
(telemetry ON). Setting them here makes the local-only guarantee
deterministic. An explicit value already in the environment wins.
"""
import os

for _var in ("CREWAI_TELEMETRY_OPT_OUT", "OTEL_SDK_DISABLED", "CREWAI_DISABLE_TELEMETRY"):
    os.environ.setdefault(_var, "true")
