"""A real run the harness starts makes its run area in the test's own temporary folder.

A run removes stale run areas from its temporary folder when it starts, so a test that left
that to the machine's folder would act on whatever an earlier, killed suite left there. This is
the check that holds the rule: it fails if a start's environment has no temporary folder of the
test's own.
"""

import importlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
real_run = importlib.import_module("rehearsal.real_run")

# argv 1: where to write its own home, which is inside its run area.
REPORTS_ITS_HOME = "import os, sys\nopen(sys.argv[1], 'w').write(os.environ['HOME'])\n"


class AHarnessStartHasATemporaryFolderOfItsOwn(real_run.RealRun):
    def test_a_run_with_no_temporary_folder_named_makes_its_run_area_under_the_tests_root(self):
        reported = os.path.join(self.place, "home")
        doc = self.document(self.script("home.py", REPORTS_ITS_HOME), [reported])
        code, _, err = self.run_to_the_end(doc)
        self.assertEqual((code, err), (0, ""))
        with open(reported) as f:
            home = os.path.realpath(f.read())
        self.assertTrue(home.startswith(os.path.join(self.root, "run-areas") + os.sep), home)
