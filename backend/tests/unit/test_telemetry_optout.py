import os


def test_importing_agents_disables_telemetry():
    import aura.agents  # noqa: F401
    assert os.environ["CREWAI_TELEMETRY_OPT_OUT"] == "true"
    assert os.environ["OTEL_SDK_DISABLED"] == "true"
