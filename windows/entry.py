if __name__ == "__main__":
    import multiprocessing

    multiprocessing.freeze_support()

    from windows.launcher import main

    raise SystemExit(main())
