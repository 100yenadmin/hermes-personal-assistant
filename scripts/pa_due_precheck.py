from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from personal_assistant.automation_workflow import script_main
script_main("due_source_check")
