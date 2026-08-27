import sys
from pathlib import Path
from app.config import settings
from app.engine import ChatterboxEngine

if len(sys.argv) != 2:
    raise SystemExit("Usage: python smoke_test.py reference.wav")
reference = Path(sys.argv[1]).resolve()
if not reference.is_file():
    raise SystemExit(f"Reference not found: {reference}")
output = settings.generated_dir / "smoke-test.wav"
ChatterboxEngine(settings.device).synthesize("This is a Chatterbox smoke test.", reference, output)
print(f"Generated {output}; listen to it before continuing with API integration.")
