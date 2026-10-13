"""
Seed script — creates the demo investor accounts and sample documents.
The API also does this automatically on startup when SEED_DEMO_DATA=true.

    python seed.py

Demo password for every seeded account = DEMO_PASSWORD (default: ChangeMe123!).
Change it before showing the portal to anyone outside your team.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from app.seed_data import seed_demo_data  # noqa: E402

if __name__ == "__main__":
    asyncio.run(seed_demo_data(verbose=True))
    print("\nSeeding complete. Change passwords before production use!")
