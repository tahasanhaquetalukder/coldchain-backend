"""Feature building shared by the training scripts and the running server.

Filled in Task 5 phase 2. Lives in backend/ (not ml/) precisely so train and serve cannot drift:
the laptop imports this file, Render imports the same file.

Past data only - a feature that reads a sample at or after the prediction time is leakage and would
produce an accuracy number no live fridge can reproduce.
"""
