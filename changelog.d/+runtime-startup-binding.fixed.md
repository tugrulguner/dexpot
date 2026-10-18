Applications now bind the scheduler at `serve()` startup using the actual GIL state after imports; late GIL changes are reported without changing the running mode.
