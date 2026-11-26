"""The reviewer's attack lists, kept as data (see the README, "Hostile-case tables").

Three tables, plain Python data with no logic: file names that break careless code
(names_table), the forms by which a core module might reach what it must not (imports_table)
and the lint-ignore spellings (suppressions_table). Tests loop them; nothing here runs.
"""
