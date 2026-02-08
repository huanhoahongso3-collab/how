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
import concurrent.futures
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
    # FIXED: Added 'r' prefix to treat backslashes literally and stop SyntaxWarnings
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
    
    # Clean up accidental hashtags at the start of output
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
    except OSError as e:
        logger.warning(f"Failed to write history: {e}")

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
        parent_pid = os.getppid()
        parent_process = psutil.Process(parent_pid)
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
            raise AuthError("GROQ_API_KEY not found in non-interactive session.")
        print("Paste your Groq API key:")
        try: api_key = input("API Key: ").strip()
        except EOFError: raise AuthError("API key input cancelled.")
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
            temperature=0.1,
        )
        return completion.choices[0].message.content
    except Exception as e:
        raise ApiError(str(e))
    finally:
        if not silent and spinner_thread:
            stop_event.set()
            spinner_thread.join()

def main():
    # Original help menu preserved
    if len(sys.argv)<2 or "--help" in sys.argv:
        header()
        print("Usage: how <question> [--silent] [--history] [--type] [--help] [--api-key]")
        print("\nOptions:")
        print("  --silent      Suppress spinner and typewriter effect")
        print("  --type        Show output with typewriter effect")
        print("  --history     Show command/question history")
        print("  --help        Show this help message and exit")
        print("  --api-key     Set the Groq API key (usage: --api-key <API_KEY>)")
        sys.exit(0)

    silent = "--silent" in sys.argv
    type_effect = "--type" in sys.argv and not silent
    if "--history" in sys.argv: show_history(); sys.exit(0)

    if "--api-key" in sys.argv:
        idx = sys.argv.index("--api-key")
        if len(sys.argv) > idx + 1 and not sys.argv[idx + 1].startswith("--"):
            new_key = sys.argv[idx + 1].strip()
            try:
                os.makedirs(CONFIG_DIR, exist_ok=True)
                with open(API_KEY_FILE, "w", encoding="utf-8") as f: f.write(new_key)
                os.chmod(API_KEY_FILE, 0o600)
                print("Groq API key replaced successfully.")
                sys.exit(0)
            except OSError as e:
                print(f"Error saving API key: {e}"); sys.exit(1)

    args = [arg for arg in sys.argv[1:] if arg not in ["--silent","--history","--type","--api-key"]]
    if not args: print("Error: No question provided."); sys.exit(1)
    question = " ".join(args)

    try: api_key = get_or_create_api_key()
    except AuthError as e: print(f"❌ Authentication Error: {e}"); sys.exit(1)

    current_dir = os.getcwd()
    current_user = getpass.getuser()
    current_os = f"{platform.system()} {platform.release()}"
    try: 
        files_list = os.listdir(current_dir)
        files = ", ".join(files_list[:20]) + ("..." if len(files_list)>20 else "")
    except OSError: files = "Error listing files"
    git_repo = "Yes" if os.path.exists(os.path.join(current_dir,".git")) else "No"
    tools = get_installed_tools()
    shell = get_current_terminal()

    # Original Rules Kept Exactly
    prompt = f"""SYSTEM:
    You are an expert, concise shell assistant. Your goal is to provide accurate, executable shell commands.

    CONTEXT:
    -  **OS:** {current_os}
    -  **Shell:** {shell}
    -  **CWD:** {current_dir}
    -  **User:** {current_user}
    -  **Git Repo:** {git_repo}
    -  **Files (top 20):** {files}
    -  **Available Tools:** {tools}

    RULES:
    1.  **Primary Goal:** Generate *only* the exact, executable shell command(s) for the `{shell}` environment.
    2.  **Context is Key:** Use the CONTEXT (CWD, Files, OS) to write specific, correct commands.
    3.  **No Banter:** Do NOT include greetings, sign-offs, or conversational filler (e.g., "Here is the command:").
    4.  **Safety:** If a command is complex or destructive (e.g., `rm -rf`, `find -delete`), add a single-line comment (`# ...`) *after* the command explaining what it does.
    5.  **Questions:** If the user asks a question (e.g., "what is `ls`?"), provide a concise, one-line answer. Do not output a command.
    6.  **Ambiguity:** If the request is unclear, ask a single, direct clarifying question. Start the line with `#`.

    REQUEST:
    {question}

    RESPONSE:
    """

    try:
        text = generate_response(api_key, prompt, silent)
        full_command = clean_response(text)
        commands = [line.strip() for line in full_command.splitlines() if line.strip()]

        if type_effect:
            for c in full_command: sys.stdout.write(c); sys.stdout.flush(); time.sleep(0.01)
            print()
        else:
            print(full_command)

        try: pyperclip.copy(full_command)
        except: pass
        log_history(question, commands)

    except Exception as e:
        print(f"\n💥 Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    try: main()
    except KeyboardInterrupt: print("\n👋 Interrupted."); sys.exit(130)
