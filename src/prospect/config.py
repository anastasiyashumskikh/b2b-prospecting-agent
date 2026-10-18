"""All tunable values live here. Limits are per step; cost is reported, never capped."""

from dataclasses import dataclass, field

WEB = ["WebSearch", "WebFetch"]


@dataclass(frozen=True)
class StepConfig:
    model: str
    tools: list[str] = field(default_factory=list)
    max_turns: int = 15


# Opus on every step: the demo volume is small and output quality matters most.
STEPS: dict[str, StepConfig] = {
    "company": StepConfig("opus", WEB, 15),
    "people": StepConfig("opus", WEB, 15),
    "verify": StepConfig("opus", WEB, 15),
    "context": StepConfig("opus", WEB, 15),
    "why": StepConfig("opus", [], 3),
    "drafts": StepConfig("opus", [], 5),
    "judge": StepConfig("opus", [], 5),
}

CARD_TTL_DAYS = 14
CALL_TIMEOUT_S = 600
RETRY_PAUSES_S = (5, 15)

# Step 0: a signal is a reason to write now, so it must be dated and recent.
SIGNAL_MAX_AGE_DAYS = 365
MAX_SIGNALS = 3

# Step 2: how fresh a source must be to confirm someone still holds the role.
FRESH_SOURCE_DAYS = 365
STALE_SOURCE_DAYS = 730
# Contact-data brokers: a hint at most, never proof that a person exists or holds a role.
DIRECTORY_DOMAINS = (
    "rocketreach.co", "zoominfo.com", "theofficialboard.com", "apollo.io", "signalhire.com",
    "contactout.com", "lusha.com", "leadiq.com", "datanyze.com", "cognism.com",
)  # fmt: skip

# Step 5: phrases that make outreach read as a template or as AI. Matched case-insensitively.
BANNED_PHRASES = (
    "i hope this finds you well", "i came across your profile", "i wanted to reach out", "touch base",
    "quick call", "synergy", "leverage", "game-changer", "game changer", "revolutionize", "revolutionise",
    "cutting-edge", "world-class", "furthermore", "moreover", "additionally", "thrilled", "excited to",
    "passionate", "what stands out", "not just", "exactly what you need", "if this is of interest",
    "should you be open", "i'll send you", "i will send you",
    "i watched", "i saw ", "i read ", "i noticed", "i listened", "i've been following",
    "nice result", "big move", "big numbers", "strong numbers", "impressive", "timely topic",
)  # fmt: skip
NOTE_MAX_CHARS = 300
SENDER_NAME_RESERVE = 22  # "[Your name]" is counted as a 22-character name, so the real note stays under 300
EMAIL_MAX_WORDS = 150
SUBJECT_MAX_WORDS = 6
