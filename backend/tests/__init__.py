"""The backend tests.

`app.main` builds the application when it is imported, and the application stops at startup
without a per-run budget (RUN_BUDGET_EUR, #30). The tests run on a local test value; a test that
needs another value, or none, passes its own settings or environment.
"""

import os

os.environ.setdefault("RUN_BUDGET_EUR", "5")
