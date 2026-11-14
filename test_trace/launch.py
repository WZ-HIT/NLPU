"""Run a test process in its own process group, cleaning up surviving children."""
import json
import os
import signal
import subprocess
import sys


def main():
    config = json.load(open(sys.argv[1], encoding="utf-8"))
    environment = dict(os.environ)
    environment.update(config["env"])
    process = subprocess.Popen(config["argv"], cwd=config["cwd"], env=environment, start_new_session=True)
    code = 124
    try:
        code = process.wait(timeout=config["timeout"])
    except subprocess.TimeoutExpired:
        pass
    finally:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()
    raise SystemExit(code)


if __name__ == "__main__":
    main()
