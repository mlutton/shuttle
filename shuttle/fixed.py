"""The fixed values: the one list the writer and any checker both read.

Adding a value here is a format version change.
"""

FORMAT_VERSION = 1

NONE = "none"  # looked, and there is nothing
CANNOT_TELL = "cannot tell"  # could not look

ENDINGS = (
    "ended_by_itself",
    "time_limit",
    "stopped_from_outside",
    "asked_for_a_human",
    "could_not_start",
    "execution_failed",
)

REASONS_BY_ENDING = {
    "ended_by_itself": (),
    "time_limit": ("time_limit",),
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
        "place_has_uncommitted_changes",
        "place_has_nested_repository",
        "statement_location_occupied",
        "no_time_limit",
        "records_location_mismatch",
        "destination_branch_not_at_opening_commit",
        "destination_branch_checked_out",
        "request_id_branch_exists",
        "reach_not_available",
        "unknown_executor",
        "unknown_setting",
        "missing_setting",
        "tool_not_installed",
        "no_login",
        "request_id_used",
        "credential_like_value",
        "gate_said_no",
        "gate_failed",
        "setup_failed",
        "freeze_failed",
        "launch_failed",
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
    "stop_record": (NONE,),
    "signal": (NONE,),
    "stopped": (NONE,),
    "request_id_used": ("id_claim",),
    "records_location_unusable": ("id_claim",),
    "unknown_executor": _INPUT_OR_DRIVER,
    "unknown_setting": _INPUT_OR_DRIVER,
    "missing_setting": _INPUT_OR_DRIVER,
    "tool_not_installed": ("executor_driver_check",),
    "no_login": ("executor_driver_check",),
    "gate_said_no": ("gates",),
    "gate_failed": ("gates",),
    "setup_failed": ("setup",),
    "freeze_failed": ("opening_freeze",),
    "launch_failed": ("launch",),
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
    "the_ending": (
        "ending",
        "reason",
        "failed_step",
        "reason_text",
        "receipt_id",
        "everything_stopped",
        "execution_version",
        "host",
    ),
    "what_execution_saw": (
        "started_at",
        "ended_at",
        "observed_runtime",
        "duration_gates",
        "duration_opening_freeze",
        "duration_executor",
        "duration_closing_freeze",
        "duration_delivery",
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
        "peak_memory",
        "processor_time",
        "session_file_kept_at",
        "teardown_failure",
        "stop_reason",
        "stop_asker",
    ),
    "what_the_executor_driver_observed": (
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
    "what_the_executor_said": (
        "statement_state",
        "statement_hash",
        "statement_location",
        "claim",
    ),
}

# The mark a stand-in step puts on what it returns.
STAND_IN_KEY = "stand_in"
