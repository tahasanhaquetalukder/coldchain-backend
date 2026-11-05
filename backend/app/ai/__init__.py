"""Server-side AI for Task 5: forecast, compressor health, relocation.

Stdlib only. This package is imported by the app process on Render, so it must never reach for
numpy, pandas or sklearn - those live in ml/ and run on the training laptop.

Deliberately imports nothing: a module that is still being built must not be able to stop the
server from starting.
"""
