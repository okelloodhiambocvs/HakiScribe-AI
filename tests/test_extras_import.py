"""Extras import smoke test: every parked module must import cleanly."""

import importlib

import pytest

EXTRA_MODULES = [
    "extras",
    "extras.explainer",
    "extras.explainer.service",
    "extras.explainer.wonder_client",
    "extras.offline",
    "extras.offline.glimmer_client",
    "extras.offline.service",
    "extras.timeline",
    "extras.timeline.image_client",
    "extras.timeline.service",
    "extras.vision",
    "extras.vision.sam_client",
    "extras.vision.service",
]


@pytest.mark.parametrize("module_name", EXTRA_MODULES)
def test_extras_module_imports(module_name):
    assert importlib.import_module(module_name) is not None
