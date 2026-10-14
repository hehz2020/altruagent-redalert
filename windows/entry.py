"""PyInstaller entry point; divert worker invocations before any UI imports."""

if __name__ == "__main__":
    import multiprocessing

    # In a frozen app sys.executable is this EXE. PyInstaller's override
    # dispatches --multiprocessing-fork before another key prompt can run.
    multiprocessing.freeze_support()

    from windows.launcher import main

    raise SystemExit(main())
