"""
Pytest configuration. Runs before any test module is imported.

Sets DISABLE_BACKGROUND_TASKS=1 so that importing `app` does not spin up
the alerts background thread - tests don't want a real polling thread
hitting the network in the background.
"""

import os

os.environ["DISABLE_BACKGROUND_TASKS"] = "1"
