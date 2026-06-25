"""Visual, time-series scenario tests for the shutter engine.

These tests simulate a day's worth of sun movement, indoor temperature and a
few special events (manual lock, fire, burglary) and render the raw inputs
together with the resolver output (cover position / tilt / reason) into PNG
charts under ``docs/images/scenarios/``. They double as executable
documentation of how the drivers and constraints behave over time.
"""
