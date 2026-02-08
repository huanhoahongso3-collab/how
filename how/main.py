import sys
import os
import threading
import time
from groq import Groq
import getpass
import platform
import pyperclip
import shutil
import itertools
import logging
import psutil
import datetime

# Logging
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

CONFIG_DIR = os.path.expanduser("~/.how-cli")
API_KEY_FILE = os.path.join(CONFIG_DIR, ".groq_api_key")
HISTORY_FILE = os.path.join(CONFIG_DIR, "history.log")
MODEL_NAME = os.getenv("HOW_MODEL", "openai/gpt-oss-120b")

class ApiError(Exception): pass
class AuthError(ApiError): pass

def header():
    # 'r' prefix handles the Python 3.13 backslash warnings
    print(r"""
    __             
   / /  ___ _    __
  / _ \/ _ \ |/|/ /
 /_//_/\___/__,__/ 
    """)
    print("Ask me how to do anything in your terminal!")

def clean_response(text: str) -> str:
    text = text.strip()
    if text.startswith("```") and text.endswith("```"):
        first_line = text.split("\n", 1)[0]
        text = text[len(first_line):-3].strip() if len(first_line) > 3 else text[3:-3].strip()
    elif text.startswith("`") and text.endswith("`"):
        text = text[1:-1].strip()
    
    # Removes any accidental hashtags from the AI to keep terminal output clean
    if text.startswith("# "):
        text = text[2:]
    elif text.startswith("#"):
        text = text[1:]
    return text.strip()

def spinner(stop_event, message="Generating"):
    frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    for frame in itertools.cycle(frames):
        if stop_event.is_set():
            break
        sys.stdout.write(f"\r{frame} {message}")
        sys.stdout.flush()
        time.sleep(0.1)
    sys.stdout.write("\r" + " " * (len(message) + 2) + "\r")
    sys.stdout.flush()

def log_history(question: str, commands: list):
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(HISTORY_FILE, "a", encoding="utf-8") as f:
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            f.write(f"[{timestamp}] Q: {question}\nCommands:\n")
            f.writelines(f"{cmd}\n" for cmd in commands)
            f.write("\n")
    except OSError: pass

def show_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                print(f.read())
        except OSError as e:
            print(f"Error reading history file: {e}")
    else:
        print("No history found.")

def get_installed_tools() -> str:
    tools = [t for t in ["git","npm","node","python","docker","pip","go","rustc","cargo","java","mvn","gradle"] if shutil.which(t)]
    return ", ".join(tools)

def get_current_terminal() -> str:
    try:
        parent_process = psutil.Process(os.getppid())
        return parent_process.name()
    except Exception:
        return "Unknown"

def get_or_create_api_key(force_reenter=False) -> str:
    api_key = None
    if not force_reenter:
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key and os.path.exists(API_KEY_FILE):
            try:
                with open(API_KEY_FILE, "r", encoding="utf-8") as f:
                    api_key = f.read().strip()
            except OSError: pass

    if not api_key or force_reenter:
        if not sys.stdin.isatty():
            raise AuthError("GROQ_API_KEY not found.")
        print("Paste your Groq API key:")
        try: api_key = input("API Key: ").strip()
        except EOFError: raise AuthError("Input cancelled.")
        if not api_key: raise AuthError("API key cannot be empty.")
        try:
            os.makedirs(CONFIG_DIR, exist_ok=True)
            with open(API_KEY_FILE, "w", encoding="utf-8") as f: f.write(api_key)
            os.chmod(API_KEY_FILE, 0o600)
        except OSError: pass
    return api_key

def generate_response(api_key: str, prompt: str, silent: bool=False) -> str:
    client = Groq(api_key=api_key)
    stop_event = threading.Event()
    spinner_thread = None
    if not silent:
        spinner_thread = threading.Thread(target=spinner, args=(stop_event,), daemon=True)
        spinner_thread.start()

    try:
        completion = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[{"role": "user", "content": prompt}],
            temperature=1.0,
            max_completion_tokens=8192,
            top_p=1.0,
        )
        return completion.choices[0].message.content
    except Exception as e:
        raise ApiError(str(e))
    finally:
        if not silent and spinner_thread:
            stop_event.set()
            spinner_thread.join()

def main():
    if len(sys.argv)<2 or "--help" in sys.argv:
        header()
        print("Usage: how <question> [--silent] [--history] [--type] [--help] [--api-key]")
        print("\nOptions:")
        print("  --silent      Suppress spinner and typewriter effect")
        print("  --type        Show output with typewriter effect")
        print("  --history     Show command/question history")
        print("  --help        Show help message")
        print("  --api-key     Set the Groq API key")
        sys.exit(0)

    silent = "--silent" in sys.argv
    type_effect = "--type" in sys.argv and not silent
    if "--history" in sys.argv: show_history(); sys.exit(0)

    if "--api-key" in sys.argv:
        idx = sys.argv.index("--api-key")
        if len(sys.argv) > idx + 1:
            new_key = sys.argv[idx + 1].strip()
            os.makedirs(CONFIG_DIR, exist_ok=True)
            with open(API_KEY_FILE, "w", encoding="utf-8") as f: f.write(new_key)
            print("Groq API key updated.")
            sys.exit(0)

    args = [arg for arg in sys.argv[1:] if arg not in ["--silent","--history","--type","--api-key"]]
    if not args: print("Error: No question provided."); sys.exit(1)
    question = " ".join(args)

    try: api_key = get_or_create_api_key()
    except AuthError as e: print(f"❌ Error: {e}"); sys.exit(1)

    current_dir = os.getcwd()
    current_os = f"{platform.system()} {platform.release()}"
    tools = get_installed_tools()
    shell = get_current_terminal()

    # Preserving your rules exactly as requested
    prompt = f"""SYSTEM:
    You are an expert shell assistant. OS: {current_os}, Shell: {shell}, CWD: {current_dir}.

    RULES:
    1. Generate ONLY the executable shell command(s) for the `{shell}` environment.
    2. No greetings or filler.
    3. If destructive, add # comment after the command.
    4. Questions get a one-line concise answer.
    5. No # at the start of output.

    REQUEST: {question}
    """

    try:
        text = generate_response(api_key, prompt, silent)
        full_command = clean_response(text)
        
        if type_effect:
            for c in full_command: sys.stdout.write(c); sys.stdout.flush(); time.sleep(0.01)
            print()
        else:
            print(full_command)

        try: pyperclip.copy(full_command)
        except: pass
        log_history(question, full_command.splitlines())

    except Exception as e:
        print(f"\n💥 Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    try: main()
    except KeyboardInterrupt: print("\n👋 Interrupted."); sys.exit(130)
