"""Free-text profile input: classifies a free-text description into the
weighting engine's five axes and applies the resulting starting weights,
the same way profile_form.py's structured form does. Coexists with that
form -- this is an alternative way to reach the same
UserProfile -> compute_weights -> sliders pipeline, not a replacement.

buurtkompas.nlu.classifier is imported lazily, inside the submit handler,
because importing it pulls in torch/sentence-transformers (~480MB RSS just
to import, per CLAUDE.md) and most sessions never use this box.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import streamlit as st

from buurtkompas.dashboard.profile_form import weights_to_slider_values
from buurtkompas.weighting.engine import (
    UserProfile,
    apply_category_mentions,
    compute_weights,
)

if TYPE_CHECKING:
    from buurtkompas.nlu.classifier import ClassificationResult

logger = logging.getLogger(__name__)

_AXIS_LABELS = {
    "age_group": "Age group",
    "has_children": "Children",
    "urgency": "Urgency",
    "budget": "Budget",
    "environment": "Environment",
}

# Display names for the "also emphasized" line: same wording as app.py's
# CATEGORY_LABELS (a test keeps them in sync; importing app here would be
# circular), and in the engine's category order.
_CATEGORY_LABELS = {
    "schools": "Education",
    "amenities": "Amenities",
    "quiet_nature": "Quiet & Nature",
    "housing": "Housing",
    "income": "Income",
    "safety": "Safety",
}

# "A sentence or two": the classifier embeds every clause of the input, so
# unbounded text would be an easy way to burn the instance's single CPU.
_MAX_CHARS = 500

_RESULT_KEY = "last_nlu_result_lines"


def _level_display(level: object) -> str:
    """has_children is a bare bool; every other axis is an enum member."""
    if isinstance(level, bool):
        return "yes" if level else "no"
    return level.value  # type: ignore[attr-defined]


def _nothing_detected(result: ClassificationResult) -> bool:
    return all(getattr(result, axis).level is None for axis in _AXIS_LABELS)


def _describe(result: ClassificationResult) -> list[str]:
    """One human-readable line per axis: what was detected and which
    reference phrase it matched, or that it fell back to the default. Kept
    as a plain function (no Streamlit calls) so it's unit-testable without
    rendering anything.
    """
    defaults = UserProfile()
    lines = []
    for axis, label in _AXIS_LABELS.items():
        match = getattr(result, axis)
        if match.level is None:
            default = _level_display(getattr(defaults, axis))
            lines.append(f"{label}: not mentioned — using default ({default})")
        else:
            lines.append(
                f"{label}: {_level_display(match.level)} "
                f'(matched "{match.matched_phrase}", similarity {match.similarity:.2f})'
            )
    return lines


def _describe_categories(mentioned: frozenset[str]) -> str | None:
    """The "also emphasized" line, or None when no category was named (so a
    result with nothing to add stays free of a pointless "none" line)."""
    if not mentioned:
        return None
    names = [label for slug, label in _CATEGORY_LABELS.items() if slug in mentioned]
    return f"Also emphasized: {', '.join(names)}"


def _nothing_matched(result: ClassificationResult, mentioned: frozenset[str]) -> bool:
    """Neither mechanism found anything. Applying the baseline profile then
    would silently move the sliders for no reason, so the caller leaves them."""
    return _nothing_detected(result) and not mentioned


def _summary_lines(
    result: ClassificationResult, mentioned: frozenset[str]
) -> list[str]:
    """Everything the "What was detected" box shows, from both mechanisms:
    one line per axis, plus an "Also emphasized" line only when a category was
    named."""
    lines = _describe(result)
    emphasized = _describe_categories(mentioned)
    if emphasized:
        lines.append(emphasized)
    if _nothing_matched(result, mentioned):
        lines.insert(
            0,
            "Nothing in your description matched — the sliders were left as they are.",
        )
    return lines


def _slider_values(profile: UserProfile, mentioned: frozenset[str]) -> dict[str, int]:
    """Both mechanisms in one step: the axis profile sets the starting
    weights, then explicitly named categories are boosted on top."""
    weights = apply_category_mentions(compute_weights(profile), mentioned)
    return weights_to_slider_values(weights)


def render_nlu_form() -> None:
    """Render the free-text box. On submit, classify the text, show what
    was detected, and apply the resulting weights through the same
    pending_slider_weights handoff profile_form.py uses -- must run before
    render_weight_sliders() in the same script execution.
    """
    st.write("**Describe your situation in your own words** — or use the form below")
    with st.form("nlu_form"):
        text = st.text_area(
            "Free-text description",
            placeholder=(
                'e.g. "Young couple, need to move quickly, tight budget, '
                'want to be in the city"'
            ),
            max_chars=_MAX_CHARS,
            label_visibility="collapsed",
        )
        submitted = st.form_submit_button("Analyze my description")

    if submitted and not text.strip():
        st.info("Type a short description first.")
    elif submitted:
        with st.spinner("Analyzing your description..."):
            try:
                # Lazy on purpose: see the module docstring.
                from buurtkompas.nlu.classifier import (
                    classify,
                    detect_mentioned_categories,
                )

                result = classify(text)
                mentioned = detect_mentioned_categories(text)
            except Exception as exc:  # heavy dependency: degrade, don't crash
                logger.exception("Free-text classification failed")
                st.session_state.pop(_RESULT_KEY, None)  # don't leave a stale summary
                st.error(
                    f"Couldn't analyze that text ({exc}). Try the form below instead."
                )
            else:
                if not _nothing_matched(result, mentioned):
                    st.session_state["pending_slider_weights"] = _slider_values(
                        result.to_profile(), mentioned
                    )
                st.session_state[_RESULT_KEY] = _summary_lines(result, mentioned)

    # Read from session_state, not a local, so the summary survives later
    # reruns (a slider nudge) until the next classification replaces it.
    if _RESULT_KEY in st.session_state:
        with st.expander(
            "What was detected (from your last description)", expanded=True
        ):
            for line in st.session_state[_RESULT_KEY]:
                st.caption(line)
