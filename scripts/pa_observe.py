#!/usr/bin/env python3
import os, sys, warnings
from pathlib import Path
with open(os.devnull, "wb") as sink: os.dup2(sink.fileno(), 2)
sys.dont_write_bytecode = True
warnings.simplefilter("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from personal_assistant.observe import main
raise SystemExit(main(sys.argv[1:]))
