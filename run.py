#!/usr/bin/env python3
"""Start StudyMate.

    python run.py

Configuration comes from the environment or a .env file at the project root —
see .env.example. No third-party packages are required.
"""

from studymate.server import main

if __name__ == "__main__":
    main()
