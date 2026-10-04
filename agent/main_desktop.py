"""Focus Agent Desktop Launcher.

Single-click launcher for the Focus Agent Desktop GUI.
"""

import sys
import os
import tkinter as tk
from app_gui import FocusAgentApp


def main():
    root = tk.Tk()
    app = FocusAgentApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
