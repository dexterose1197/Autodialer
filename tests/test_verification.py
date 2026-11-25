import wave

import pytest
from pydantic import ValidationError

from autodialer.verification import (
    DEFAULT_WORKFLOW, FixtureTranscriber, Rule, SimulatedIVR, Workflow, classify,
)


def test_literal_rules_normalize_words_and_detect_conflicts():
    workflow = Workflow(name="Review", digits="12", rules=[
        Rule(label="Confirmed", phrases=["Appointment confirmed"]),
        Rule(label="Change", phrases=["call back"]),
    ])
    assert classify(workflow, "APPOINTMENT, confirmed!")[0] == "Confirmed"
    assert classify(workflow, "Appointment confirmedly")[0] is None
    label, reason = classify(workflow, "Appointment confirmed, please call back.")
    assert label is None and "Conflicting" in reason
    assert classify(workflow, " ") == (None, "No speech was transcribed.")


def test_workflow_rejects_ambiguous_configuration():
    with pytest.raises(ValidationError):
        Workflow(name="Review", digits="1A", rules=DEFAULT_WORKFLOW.rules)
    with pytest.raises(ValidationError):
        Workflow(name="Review", digits="12", rules=[
            Rule(label="Same", phrases=["first"]), Rule(label="same", phrases=["second"]),
        ])


@pytest.mark.parametrize("digits,scenario,fixture", [
    ("12", "confirmed", "confirmed"),
    ("12", "action_required", "action_required"),
    ("12", "ambiguous", "ambiguous"),
    ("1", "confirmed", "menu"),
])
def test_simulator_recordings_are_playable(digits, scenario, fixture):
    recording = SimulatedIVR().capture("+12025550101", digits, scenario)
    assert recording.fixture == fixture
    with wave.open(str(recording.path), "rb") as audio:
        assert (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) == (1, 2, 16000)
        assert audio.getnframes() > 16_000
    assert FixtureTranscriber().transcribe(recording)
