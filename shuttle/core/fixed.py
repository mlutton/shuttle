"""The fixed values: the one list the writer and any checker both read.

Adding a value here changes the record version, and for a value the input document may name, the input version.
"""

from typing import Final

# Two version numbers, each checked on its own. The input document carries one (its key is
# `format_version`); the records carry the other (the header's `record_version`).
INPUT_VERSION = 1
RECORD_VERSION = 5
# The version of the notice execution adds to the instruction of a kind that expects a statement
# (shuttle.core.notice). It changes whenever the notice's fixed words do.
NOTICE_VERSION = 1

# The four states of a receipt field, in the one list. A field is a pair of a state and a value.
VALUE = "value"  # looked, and found this
NONE = "none"  # looked, and there is nothing
CANNOT_TELL = "cannot tell"  # could not look
NOT_BUILT = "not built"  # the step behind this field is still a stand-in
# While stand-ins exist NOT_BUILT is a state; when the last one is replaced, remove it from here.
STATES = (VALUE, NONE, CANNOT_TELL, NOT_BUILT)

# The characters a request id (and an environment variable's name) may hold. A dot is not one of
# them, so a record's name, `<id>.<kind>.json`, reads back to its id and kind unambiguously.
ID_CHARACTERS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"

# The kinds of record that live beside each other under one request id. Only the request and
# outcome records are written; the stop record and the liveness file have their names reserved
# here and nothing more is defined for them yet.
RECORD_KINDS = ("request", "outcome", "stop", "liveness")

ENDINGS = (
    "ended_by_itself",
    "time_limit",
    "memory_limit",
    "stopped_from_outside",
    "asked_for_a_human",
    "could_not_start",
    "execution_failed",
)

REASONS_BY_ENDING = {
    "ended_by_itself": (),
    "time_limit": ("time_limit",),
    "memory_limit": ("memory_limit",),
    "stopped_from_outside": ("stop_record", "signal"),
    "asked_for_a_human": (),
    "could_not_start": (
        "unknown_format_version",
        "unknown_field",
        "unknown_kind",
        "instruction_hash_mismatch",
        "reference_missing",
        "reference_hash_mismatch",
        "place_missing",
        "place_not_a_git_checkout",
        "place_has_filter_attribute",
        "place_has_uncommitted_changes",
        "place_has_nested_repository",
        "statement_location_occupied",
        "statement_location_in_records",
        "no_time_limit",
        "memory_cap_unavailable",
        "records_location_mismatch",
        "destination_branch_not_at_opening_commit",
        "destination_branch_checked_out",
        "request_id_branch_exists",
        "reach_not_valid",
        "visible_not_absolute",
        "visible_missing",
        "visible_not_a_folder",
        "visible_overlaps_the_records",
        "visible_overlaps_the_box",
        "visible_overlaps_the_runtime_folder",
        "visible_overlaps_the_home_folder",
        "unknown_executor",
        "unknown_setting",
        "missing_setting",
        "tool_not_installed",
        "program_not_visible",
        "no_login",
        "request_id_used",
        "credential_like_value",
        "gate_said_no",
        "gate_failed",
        "setup_failed",
        "freeze_failed",
        "launch_failed",
        "program_not_started",
        "stopped",
        "records_location_unusable",
        "execution_error",
    ),
    "execution_failed": (
        "stop_not_confirmed",
        "closing_freeze_failed",
        "destination_changed",
        "delivery_failed",
        "lost",
        "execution_error",
    ),
}

REASONS = tuple(dict.fromkeys(r for ending in ENDINGS for r in REASONS_BY_ENDING[ending]))

# Failed steps, by the ending that may name them. "gates" is a step for
# "could not start"; "record" is not a step.
STEPS_BY_ENDING = {
    "could_not_start": (
        "gates",
        "input_check",
        "executor_driver_check",
        "id_claim",
        "setup",
        "opening_freeze",
        "launch",
    ),
    "execution_failed": ("stop_not_confirmed", "closing_freeze", "delivery"),
}

STEPS = tuple(s for steps in STEPS_BY_ENDING.values() for s in steps)

# Which failed step each reason may sit beside. "none" for a reason that names no step.
_INPUT = ("input_check",)
_INPUT_OR_DRIVER = ("input_check", "executor_driver_check")
STEPS_FOR_REASON = {
    "time_limit": (NONE,),
    "memory_limit": (NONE,),
    "stop_record": (NONE,),
    "signal": (NONE,),
    "stopped": (NONE,),
    "request_id_used": ("id_claim",),
    "records_location_unusable": ("id_claim",),
    "unknown_executor": _INPUT_OR_DRIVER,
    "unknown_setting": _INPUT_OR_DRIVER,
    "missing_setting": _INPUT_OR_DRIVER,
    "tool_not_installed": ("executor_driver_check",),
    "program_not_visible": ("executor_driver_check",),
    "no_login": ("executor_driver_check",),
    "gate_said_no": ("gates",),
    "gate_failed": ("gates",),
    "setup_failed": ("setup",),
    "freeze_failed": ("opening_freeze",),
    "launch_failed": ("launch",),
    "program_not_started": ("launch",),
    "stop_not_confirmed": ("stop_not_confirmed",),
    "closing_freeze_failed": ("closing_freeze",),
    "destination_changed": ("delivery",),
    "delivery_failed": ("delivery",),
    "lost": (CANNOT_TELL,),
    # Execution itself broke: the step that was running, or cannot tell when that is not known.
    "execution_error": STEPS + (CANNOT_TELL,),
}
for _reason in REASONS:
    STEPS_FOR_REASON.setdefault(_reason, _INPUT)
del _reason

# The receipt: four groups, by who knows the fact.
RECEIPT_GROUPS = {
    "ending": (
        "ending",
        "reason",
        "failed_step",
        "reason_text",
        "receipt_id",
        "everything_stopped",
    ),
    "execution": (
        "execution_version",
        "host",
        "started_at",
        "ended_at",
        "observed_runtime",
        "duration_gates_seconds",
        "duration_opening_freeze_seconds",
        "duration_executor_seconds",
        "duration_closing_freeze_seconds",
        "duration_delivery_seconds",
        "input_hash",
        "reference_hashes",
        "fingerprint_before",
        "fingerprint_after",
        "changed_nothing",
        "files_added",
        "files_changed",
        "files_deleted",
        "files_list_kept_file",
        "delivered",
        "delivery_branch",
        "delivery_branch_reason",
        "exit_code",
        "signal",
        "peak_memory_bytes",
        "processor_time_seconds",
        "session_file_kept_at",
        "standard_output_kept",
        "standard_error_kept",
        "final_message_kept",
        "teardown_failure",
        "stop_reason",
        "stop_asker",
    ),
    "executor_driver": (
        "executor_driver_name",
        "executor_driver_version",
        "tool_version",
        "model",
        "effort",
        "tokens_in",
        "tokens_out",
        "tokens_cached",
        "activity",
        "session_id",
        "refused_actions",
        "quota_level",
        "vendor_limit_reached",
        "vendor_limit_reset",
        "tool_made_own_commits",
        "load_lists_differ",
        "load_lists_kept_file",
        "changed_self_loaded_file",
        "waiting_question",
    ),
    "executor": (
        "statement_state",
        "statement_hash",
        "statement_location",
        "claim",
    ),
}

# The mark a stand-in step puts on what it returns.
STAND_IN_KEY: Final = "stand_in"
