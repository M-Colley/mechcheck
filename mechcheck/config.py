"""Configuration: defaults, profiles, venue packs, user overrides.

Precedence, lowest to highest::

    built-in defaults  <  profile  <  venue pack  <  mechcheck.yaml  <  CLI flags

A venue pack (``mechcheck/venues/chi.yaml`` and friends) is pure data: adding a
venue must never require touching Python.  That is deliberate -- submission
requirements change every year, and a data file can be updated by whoever reads
the new call for papers.
"""

from __future__ import annotations

import copy
import os
from dataclasses import dataclass, field

from mechcheck import minyaml
from mechcheck.model import Severity

CONFIG_NAMES = ("mechcheck.yaml", "mechcheck.yml", ".mechcheck.yaml", ".mechcheck.yml")

VENUE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "venues")

#: Profiles select *which* rules make sense for a document, not how strict they
#: are.  Strictness is the ``stage`` (draft / submission / final).
PROFILES: dict = {
    "thesis": {
        "description": "Bachelor's/Master's thesis: structure, cross-references, abbreviations, bibliography.",
        "disable": ["VEN*", "ANON*"],
    },
    "paper": {
        "description": "Conference or journal paper without a specific venue pack.",
        "disable": ["THE*"],
    },
    "paper-anonymous": {
        "description": "Paper under double-anonymous review: adds the anonymity sweep.",
        "disable": ["THE*"],
        "anonymous": True,
    },
    "camera-ready": {
        "description": "Final version: everything, including PDF-level and policy checks.",
        "disable": ["THE*"],
        "stage": "final",
    },
    "all": {
        "description": "Every rule, for developing the checker itself.",
        "disable": [],
    },
}

#: Stages tighten severities without changing the rule set.
STAGES: dict = {
    "draft": {"promote": [], "demote": ["*"]},          # nothing blocks an early draft
    "submission": {"promote": [], "demote": []},        # rules' own severities
    "final": {"promote": ["*"], "demote": []},          # every warning becomes an error
}

DEFAULTS: dict = {
    "profile": "thesis",
    "stage": "submission",
    "venue": None,
    "language": "en",
    "main": None,
    "fail_on": "error",
    #: Most findings shown per rule; 0 shows everything. A systematic
    #: habit should cost one entry and a count, not three hundred.
    "max_per_rule": 10,
    "anonymous": False,
    "disable": [],
    "enable": [],
    "severity": {},
    "rules": {},
    #: The project's own vocabulary: groups of words that name one concept,
    #: optionally with the one this project uses. See mechcheck/rules/terminology.py.
    "terminology": [],
    "ignore_paths": ["build/**", "out/**", ".git/**", "**/node_modules/**"],
}


def _coerce_shapes(data: dict) -> None:
    """Force the keys whose shape the rest of the code relies on.

    A configuration file is user input, and it is read by a parser that is
    documented never to raise. Something has to stand between "the file says
    something odd" and "every rule crashes halfway through the run", and this
    is it: a wrong type degrades to the empty default, and a bare scalar where
    a list belongs is read as a list of one, which is what was meant.
    """
    for key in ("disable", "enable", "ignore_paths", "terminology"):
        value = data.get(key)
        if isinstance(value, str):
            value = value.strip()
            data[key] = [value] if value and value not in ("[]", "{}") else []
        elif not isinstance(value, list):
            data[key] = []
    for key in ("severity", "rules"):
        if not isinstance(data.get(key), dict):
            data[key] = {}


@dataclass
class Config:
    data: dict = field(default_factory=dict)
    path: str | None = None
    venue_data: dict = field(default_factory=dict)

    # -- loading ----------------------------------------------------------- #

    @classmethod
    def load(cls, root: str, explicit: str | None = None, overrides: dict | None = None) -> "Config":
        # deepcopy, not dict(): _merge writes into nested dicts, so a shallow
        # copy would let one project's severity overrides leak into every later
        # Config in the same process -- which is exactly what the weekly digest
        # does when it checks twenty repositories in one run.
        data = copy.deepcopy(DEFAULTS)
        user_path = explicit or cls.find(root)
        user: dict = minyaml.load(user_path) if user_path else {}

        profile_name = (overrides or {}).get("profile") or user.get("profile") or data["profile"]
        profile = PROFILES.get(profile_name, {})

        venue_name = (overrides or {}).get("venue") or user.get("venue") or profile.get("venue")
        venue_data: dict = {}
        if venue_name:
            venue_data = load_venue(venue_name)

        for layer in (profile, venue_data.get("config", {}), user, overrides or {}):
            _merge(data, {k: v for k, v in (layer or {}).items() if v is not None})

        data["profile"] = profile_name
        data["venue"] = venue_name
        _coerce_shapes(data)
        cfg = cls(data=data, path=user_path, venue_data=venue_data)
        return cfg

    @staticmethod
    def find(root: str) -> str | None:
        for name in CONFIG_NAMES:
            cand = os.path.join(root, name)
            if os.path.isfile(cand):
                return cand
        return None

    # -- accessors --------------------------------------------------------- #

    @property
    def profile(self) -> str:
        return str(self.data.get("profile") or "thesis")

    @property
    def stage(self) -> str:
        return str(self.data.get("stage") or "submission")

    @property
    def venue(self):
        return self.data.get("venue")

    @property
    def language(self) -> str:
        return str(self.data.get("language") or "en")

    @property
    def anonymous(self) -> bool:
        return bool(self.data.get("anonymous"))

    @property
    def max_per_rule(self) -> int:
        try:
            return max(0, int(self.data.get("max_per_rule", 10)))
        except (TypeError, ValueError):
            return 10

    @property
    def fail_on(self) -> Severity:
        return Severity.parse(self.data.get("fail_on", "error"), Severity.ERROR)

    def rule_option(self, rule_id: str, key: str, default=None):
        """Per-rule option, with venue packs able to supply defaults."""
        rules = self.data.get("rules") or {}
        entry = rules.get(rule_id) or {}
        if isinstance(entry, dict) and key in entry:
            return entry[key]
        venue_rules = (self.venue_data.get("rules") or {})
        ventry = venue_rules.get(rule_id) or {}
        if isinstance(ventry, dict) and key in ventry:
            return ventry[key]
        return default

    def severity_for(self, rule_id: str) -> Severity:
        from mechcheck.model import REGISTRY

        rule = REGISTRY.get(rule_id)
        base = rule.meta.severity if rule else Severity.WARN

        overrides = self.data.get("severity") or {}
        if rule_id in overrides:
            return Severity.parse(overrides[rule_id], base)
        for pattern, value in overrides.items():
            if _glob(rule_id, str(pattern)):
                return Severity.parse(value, base)

        # A venue pack may raise the stakes on a rule -- ASSETS desk-rejects an
        # inaccessible submission, so it makes the accessibility rules errors.
        # This was read by the browser engine and not here, which meant the two
        # gave different answers for the same venue. The project's own file
        # still wins, and the stage still applies on top.
        venue_severity = self.venue_data.get("severity")
        if isinstance(venue_severity, dict) and venue_severity:
            if rule_id in venue_severity:
                base = Severity.parse(venue_severity[rule_id], base)
            else:
                for pattern, value in venue_severity.items():
                    if _glob(rule_id, str(pattern)):
                        base = Severity.parse(value, base)
                        break

        stage = STAGES.get(self.stage, {})
        if any(_glob(rule_id, p) for p in stage.get("promote", [])):
            return Severity.ERROR if base >= Severity.WARN else base
        if any(_glob(rule_id, p) for p in stage.get("demote", [])):
            return Severity.INFO if base >= Severity.WARN else base
        return base

    def enabled(self, rule_id: str) -> bool:
        enable = [str(p) for p in (self.data.get("enable") or [])]
        disable = [str(p) for p in (self.data.get("disable") or [])]
        if any(_glob(rule_id, p) for p in enable):
            return True
        if any(_glob(rule_id, p) for p in disable):
            return False
        return True

    def venue_field(self, *path, default=None):
        """Read a nested value out of the venue pack, e.g. ``('length', 'pages')``."""
        node = self.venue_data
        for key in path:
            if not isinstance(node, dict) or key not in node:
                return default
            node = node[key]
        return node


def _glob(value: str, pattern: str) -> bool:
    import fnmatch

    return fnmatch.fnmatch(value, pattern) or value == pattern


def _merge(base: dict, extra: dict) -> dict:
    """Deep-merge ``extra`` into ``base``; lists replace, dicts merge."""
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _merge(base[key], value)
        else:
            base[key] = value
    return base


def load_venue(name: str) -> dict:
    """Load a venue pack by name or path. Unknown names yield ``{}``."""
    if not name:
        return {}
    if os.path.isfile(name):
        return minyaml.load(name)
    safe = str(name).strip().lower().replace(" ", "-")
    cand = os.path.join(VENUE_DIR, safe + ".yaml")
    if os.path.isfile(cand):
        return minyaml.load(cand)
    return {}


def available_venues() -> list:
    try:
        return sorted(
            f[:-5] for f in os.listdir(VENUE_DIR)
            if f.endswith(".yaml") and not f.startswith("_")
        )
    except OSError:
        return []
