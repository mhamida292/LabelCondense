"""The window. One state at a time, two tabs, nothing else."""
import pathlib, queue, sys, tkinter as tk
from tkinter import ttk, filedialog, messagebox

import job as jobmod
import logstore
import platform_bits

STATES = ("idle", "working", "done", "failed")

class App:
    def __init__(self, root):
        self.root = root
        root.title("Packing Slips")
        root.minsize(460, 300)
        self.queue = queue.Queue()
        self.state = "idle"
        self.current_tab = "run"
        self.badge_visible = False
        self.src = None
        self.result = None

        bar = ttk.Frame(root); bar.pack(fill="x")
        self.run_btn = ttk.Button(bar, text="Run", command=lambda: self.tab("run"))
        self.logs_btn = ttk.Button(bar, text="Logs", command=lambda: self.tab("logs"))
        self.run_btn.pack(side="left"); self.logs_btn.pack(side="left")

        self.panes = {
            "run": ttk.Frame(root),
            "logs": ttk.Frame(root),
        }
        self.frames = {name: ttk.Frame(self.panes["run"]) for name in STATES}
        self._build_idle(self.frames["idle"])

        self.panes["run"].pack(fill="both", expand=True)
        self.show("idle")

    # ---------------------------------------------------------- navigation
    def tab(self, which):
        self.current_tab = which
        for name, pane in self.panes.items():
            pane.pack_forget()
        self.panes[which].pack(fill="both", expand=True)
        if which == "logs":
            self.badge_visible = False
            self.logs_btn.configure(text="Logs")
            self.refresh_logs()

    def show(self, name):
        self.state = name
        for f in self.frames.values():
            f.pack_forget()
        self.frames[name].pack(fill="both", expand=True, padx=24, pady=20)

    def mark_failure(self):
        self.badge_visible = True
        self.logs_btn.configure(text="Logs ●")

    def refresh_logs(self):
        pass          # Task 9

    # ---------------------------------------------------------------- idle
    def _build_idle(self, f):
        ttk.Label(f, text="Drop a Whatnot export here",
                  font=("TkDefaultFont", 12)).pack(pady=(28, 14))
        ttk.Button(f, text="Choose file…", command=self.pick_file).pack()
        ttk.Label(f, text="Combined Labels + Packing Slips, straight from Whatnot.",
                  foreground="#6a6d73").pack(pady=(16, 0))

    def pick_file(self, path=None):
        if path is None:
            path = filedialog.askopenfilename(
                title="Choose a Whatnot export",
                filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")])
        if not path:
            return
        self.src = pathlib.Path(path)
        self.start()

    def start(self):
        pass          # Task 8

def main():
    root = tk.Tk()
    app = App(root)
    if len(sys.argv) > 1:                 # dropped on the icon
        app.pick_file(sys.argv[1])
    root.mainloop()

if __name__ == "__main__":
    main()
