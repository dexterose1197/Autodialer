import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, Field, field_validator, model_validator

FIXTURES = Path(__file__).with_name("fixtures")
CATALOG = json.loads((FIXTURES / "catalog.json").read_text(encoding="utf-8"))
SCENARIOS = tuple(name for name in CATALOG if name != "menu")
UNSUPPORTED_TEXT = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]")


def check_exportable_text(value: str) -> str:
    if UNSUPPORTED_TEXT.search(value):
        raise ValueError("Remove unsupported control characters.")
    return value


def normalize(text: str) -> str:
    return " ".join(re.findall(r"\w+", text.casefold()))


class Rule(BaseModel):
    label: str = Field(min_length=1, max_length=60)
    phrases: list[str] = Field(min_length=1, max_length=20)

    @field_validator("label")
    @classmethod
    def clean_label(cls, label: str) -> str:
        if not label.strip():
            raise ValueError("A label cannot be blank.")
        return check_exportable_text(label.strip())

    @field_validator("phrases")
    @classmethod
    def check_phrases(cls, phrases: list[str]) -> list[str]:
        if any(len(phrase) > 160 or not normalize(phrase) for phrase in phrases):
            raise ValueError("Use phrases of 1–160 characters containing words.")
        return [phrase.strip() for phrase in phrases]


class Workflow(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    digits: str = Field(max_length=20, pattern=r"^[0-9*#]*$")
    rules: list[Rule] = Field(min_length=1, max_length=20)

    @field_validator("name")
    @classmethod
    def clean_name(cls, name: str) -> str:
        if not name.strip():
            raise ValueError("A workflow name cannot be blank.")
        return name.strip()

    @model_validator(mode="after")
    def unique_labels(self):
        labels = [rule.label.casefold() for rule in self.rules]
        if len(set(labels)) != len(labels):
            raise ValueError("Rule labels must be unique.")
        return self


DEFAULT_WORKFLOW = Workflow(
    name="Appointment verification",
    digits="12",
    rules=[
        Rule(label="Confirmed", phrases=["appointment is confirmed", "appointment has been confirmed"]),
        Rule(label="Action required", phrases=["contact the office", "update your appointment"]),
    ],
)


@dataclass(frozen=True)
class Recording:
    fixture: str
    path: Path
    review_reason: str | None = None


class TelephonyProvider(Protocol):
    def capture(self, destination: str, digits: str, scenario: str) -> Recording: ...


class SimulatedIVR:
    def capture(self, destination: str, digits: str, scenario: str) -> Recording:
        if scenario not in SCENARIOS:
            raise ValueError("Unknown simulation scenario.")
        fixture = scenario if digits == "12" else "menu"
        review_reason = "The configured digits did not reach verification." if fixture == "menu" else None
        return Recording(fixture, FIXTURES / f"{fixture}.wav", review_reason)


class Transcriber(Protocol):
    name: str

    def transcribe(self, recording: Recording) -> str: ...


class FixtureTranscriber:
    name = "fixture transcript"

    def transcribe(self, recording: Recording) -> str:
        return CATALOG[recording.fixture]


class OfflineWhisper:
    name = "Faster Whisper"

    def __init__(self, model_dir: Path):
        self.model_dir = model_dir.resolve()
        for filename in ("model.bin", "config.json", "tokenizer.json", "vocabulary.txt"):
            if not (self.model_dir / filename).is_file():
                raise ValueError(f"The local model is missing {filename}.")
        self.model = None

    def transcribe(self, recording: Recording) -> str:
        if self.model is None:
            from faster_whisper import WhisperModel

            self.model = WhisperModel(
                str(self.model_dir), local_files_only=True, device="cpu", compute_type="int8"
            )
        segments, _ = self.model.transcribe(
            str(recording.path), language="en", beam_size=5, condition_on_previous_text=False
        )
        return " ".join(segment.text.strip() for segment in segments).strip()


def classify(workflow: Workflow, transcript: str) -> tuple[str | None, str]:
    words = f" {normalize(transcript)} "
    matches = [
        rule.label
        for rule in workflow.rules
        if any(f" {normalize(phrase)} " in words for phrase in rule.phrases)
    ]
    if len(matches) == 1:
        return matches[0], "Matched a workflow rule."
    if matches:
        return None, f"Conflicting rules matched: {', '.join(matches)}."
    return None, "No workflow rule matched." if transcript.strip() else "No speech was transcribed."
