"""Which functions in checks/ that take file names are run against the names table.

The rule is tests/by_value/test_name_functions.py: it reads checks/*.py with `ast` and fails on
a function with a parameter that may carry names or paths (see NAME_PARAMETERS there) unless
the function is a key here. Keys are "module.function" (module: the file's name without .py).

- TABLE_TESTED: key to the test that runs the function against every row of the names table,
  as "<folder>/<file>::<Class>.<method>" under tests/. The test has to exist.
- EXEMPT: key to the reason the function does not carry file names. A reason is required.
"""

NAMES_TEST = "by_value/test_names_table.py"

TABLE_TESTED = {
    "names.escape_name": f"{NAMES_TEST}::EscapeNameTest.test_escape_name_renders_every_name_as_one_line_with_no_control_or_direction_character",
    "names.fenced": f"{NAMES_TEST}::FencedTest.test_fenced_gives_exactly_two_fence_lines_for_any_subset_of_the_names",
    "guards.parse_name_status": f"{NAMES_TEST}::GitOutputTest.test_parse_name_status_returns_every_name_whole_in_order_for_any_name_git_can_carry",
    "guards.is_guard": f"{NAMES_TEST}::GuardDecisionTest.test_is_guard_is_true_for_any_name_in_a_guard_folder_and_false_for_a_look_alike",
    "guards.guard_changes": f"{NAMES_TEST}::GuardDecisionTest.test_guard_changes_lists_each_guard_name_once_and_whole_and_no_look_alike",
    "guards.render_summary": f"{NAMES_TEST}::GuardDecisionTest.test_render_summary_lists_each_name_on_one_line_inside_one_block_of_two_fences",
    "fixmode.changed_files": f"{NAMES_TEST}::FixModeTest.test_changed_files_lists_each_changed_name_once_whole_and_in_order",
    "fixmode.render_lines": f"{NAMES_TEST}::FixModeTest.test_render_lines_gives_each_name_one_line_and_counts_the_files",
    "fixmode.failed_from_diagnostics": f"{NAMES_TEST}::FixModeTest.test_failed_from_diagnostics_gives_each_name_relative_to_the_root_once_and_whole",
    "fixmode.failed_from_format_output": f"{NAMES_TEST}::FixModeTest.test_failed_from_format_output_names_only_the_files_the_formatter_named",
    "fixmode.remaining_findings": f"{NAMES_TEST}::FixModeTest.test_remaining_findings_gives_each_name_on_one_line_and_no_two_alike",
    "fixmode.links_to_hash": f"{NAMES_TEST}::FixModeTest.test_links_to_hash_returns_each_link_once_whole_and_counts_links_to_one_file_once",
    "fixmode.is_bytecode": f"{NAMES_TEST}::FixModeTest.test_is_bytecode_is_true_only_for_a_pyc_file_in_a_folder_named_exactly_pycache",
    "fixmode.snapshot": f"{NAMES_TEST}::TheFilesystemTest.test_snapshot_hashes_each_file_under_its_own_whole_path_once",
    "fixmode.tree_entries": f"{NAMES_TEST}::TheFilesystemTest.test_snapshot_hashes_each_file_under_its_own_whole_path_once",
    "fixmode.file_hash": f"{NAMES_TEST}::TheFilesystemTest.test_file_hash_of_a_name_that_is_not_there_is_none_not_an_error",
    "report.find_markers": f"{NAMES_TEST}::ReportTest.test_find_markers_names_the_file_whole_in_each_marker_and_problem",
    "report.normalize_coverage": f"{NAMES_TEST}::ReportTest.test_normalize_coverage_gives_each_file_under_its_whole_path_relative_to_the_root",
    "report.merge_rows": f"{NAMES_TEST}::ReportTest.test_merge_rows_gives_one_row_for_each_walked_name_whole_and_in_order",
    "report.render_coverage": f"{NAMES_TEST}::ReportTest.test_render_coverage_gives_each_file_one_line_and_no_two_alike",
    "report.render_report": f"{NAMES_TEST}::ReportTest.test_render_report_keeps_every_name_inside_a_fenced_block_and_escaped",
    "report.coverage_config": f"{NAMES_TEST}::ReportTest.test_coverage_config_keeps_a_root_and_a_data_file_whole_in_the_toml",
    "report.walked_files": f"{NAMES_TEST}::TheFilesystemTest.test_walked_files_lists_each_python_file_once_whole_with_slashes_in_order",
    "report.source_markers": f"{NAMES_TEST}::TheFilesystemTest.test_source_markers_gives_each_marker_and_problem_with_the_file_s_whole_name",
    "report.analyse_unmeasured": f"{NAMES_TEST}::TheFilesystemTest.test_analyse_unmeasured_gives_each_file_under_its_whole_path",
}

EXEMPT = {
    "report.commit_text": "its `facts` are the pull request's event values (commit ids), not file names",
    "report.log_line": "it prints two numbers and the Python version from the report's facts; no name",
    "report.ranges": "its `lines` are line numbers, not file names",
    "report.git_commit": "shell: runs git in the project's own root folder, which the caller chose; it reads no name from the changed tree",
    "report._run": "shell: runs a tool with the project's root folder as its working folder; no name from the changed tree",
    "report.gather": "shell: runs the tools and calls the table-tested functions above with what they return; its own `root` is the project's folder",
}
