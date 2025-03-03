import subprocess
import sys
import time
import re
from datetime import datetime

def run_command(command):
    result = subprocess.run(command, capture_output=True, text=True)
    return result.stdout.strip()

def main():
    id = "nl.traverse_research.evolve"
    path = "/sdcard/Android/data/nl.traverse_research.evolve/files"

    # Get Evolve UID
    packages = run_command(["adb", "shell", "pm", "list", "packages", "-U", id])
    evolve_uid = re.search(r"uid:(\d+)", packages)
    if not evolve_uid:
        print("Evolve does not appear to be installed")
        sys.exit(1)
    evolve_uid = evolve_uid.group(1)

    # Get current timestamp
    logcat_ts = run_command(["adb", "shell", "date", "'+%m-%d %T.000'"])

    # Prepare command line arguments
    cmd_line = " ".join(f"'{arg}'" for arg in sys.argv[1:])
    
    # Start the activity
    result = run_command(["adb", "shell", f"am start -W -a android.intent.action.MAIN -n {id}/.EvolveActivity -e cmdLine \"{cmd_line}\""])
    status = re.search(r"Status: (.+)", result)
    
    if "Warning: Activity not started, intent has been delivered to currently running top-most instance." in result:
        print("Evolve is already running. Please shut it down first and try again.")
        sys.exit(1)
    elif not status or status.group(1) != "ok":
        print(f"Failed to launch activity: {result}")
        sys.exit(1)

    moment = datetime.now().strftime("%Y%m%d_%H%M%S")
    pull_suggestion = f"evolve-results-{moment}"
    
    print(f"Started Evolve on Android. When the benchmark finishes, manually pull the specified files from {path} using adb pull or MTP.")
    print("\nStarting logcat in 4 seconds")

    time.sleep(4)

    subprocess.run(["adb", "logcat", "-v", "color", "-T", logcat_ts, "--uid", evolve_uid])

if __name__ == "__main__":
    main()
