# Present so pytest puts the repository root on sys.path, making `backend`
# importable from the tests regardless of how pytest is invoked.
import os

# Don't kick off the background TTS model download when the app starts up under
# the test client — keep the suite offline and fast.
os.environ.setdefault("LETTURA_NO_WARMUP", "1")
