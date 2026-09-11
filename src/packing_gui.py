"""The window. One state at a time, two tabs, nothing else."""
import datetime as dt, os, pathlib, queue, sys, threading, tkinter as tk
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
        self.dest = None
        self._after_id = None
        root.protocol("WM_DELETE_WINDOW", self.on_close)

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
        self._build_working(self.frames["working"])
        self._build_done(self.frames["done"])
        self._build_failed(self.frames["failed"])

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

    # ------------------------------------------------------------- working
    def _build_working(self, f):
        self.file_text = tk.StringVar(value="")
        self.progress_text = tk.StringVar(value="")
        self.stage_text = tk.StringVar(value="")
        ttk.Label(f, textvariable=self.file_text,
                  font=("TkDefaultFont", 10, "bold")).pack(pady=(28, 12))
        self.bar = ttk.Progressbar(f, mode="determinate", length=380)
        self.bar.pack()
        ttk.Label(f, textvariable=self.progress_text,
                  foreground="#6a6d73").pack(pady=(10, 2))
        ttk.Label(f, textvariable=self.stage_text, foreground="#6a6d73").pack()

    def _build_done(self, f):
        self.stats_text = tk.StringVar(value="")
        ttk.Label(f, text="✓  Ready to print", foreground="#1f7a3f",
                  font=("TkDefaultFont", 13, "bold")).pack(pady=(26, 10))
        ttk.Label(f, textvariable=self.stats_text, foreground="#6a6d73",
                  justify="center").pack()
        row = ttk.Frame(f); row.pack(pady=16)
        ttk.Button(row, text="Print", command=self.do_print).pack(side="left", padx=5)
        ttk.Button(row, text="Do another", command=self.reset).pack(side="left", padx=5)
        ttk.Button(f, text="See the full report",
                   command=lambda: self.tab("logs")).pack()

    def _build_failed(self, f):
        self.fail_text = tk.StringVar(value="")
        ttk.Label(f, text="✗  DO NOT PRINT", foreground="#b3261e",
                  font=("TkDefaultFont", 13, "bold")).pack(pady=(26, 10))
        ttk.Label(f, text="This export failed its checks. Nothing was saved.",
                  justify="center").pack()
        ttk.Label(f, textvariable=self.fail_text, foreground="#6a6d73").pack(pady=(6, 0))
        row = ttk.Frame(f); row.pack(pady=16)
        ttk.Button(row, text="See what failed",
                   command=lambda: self.tab("logs")).pack(side="left", padx=5)
        ttk.Button(row, text="Do another", command=self.reset).pack(side="left", padx=5)

    # ----------------------------------------------------------------- run
    def default_name(self):
        return dt.date.today().strftime("%Y-%m-%d-slips.pdf")

    def ask_destination(self):
        """Ask until we get somewhere writable, or the user gives up. Checking
        now costs a second; checking after the build costs ninety."""
        while True:
            dest = filedialog.asksaveasfilename(
                title="Save print-ready PDF as…",
                initialfile=self.default_name(),
                defaultextension=".pdf",
                filetypes=[("PDF files", "*.pdf")])
            if not dest:
                return None               # cancelled — costs nothing
            d = pathlib.Path(dest)
            if d.parent.is_dir() and os.access(d.parent, os.W_OK):
                return d
            messagebox.showerror(
                "Can't save there",
                f"{d.parent} can't be written to. Choose another folder.")

    def start(self):
        dest = self.ask_destination()
        if dest is None:
            self.show("idle")
            return
        self.file_text.set(self.src.name)
        self.progress_text.set("")
        self.stage_text.set("starting…")
        self.bar.configure(value=0, maximum=100)
        self.log_lines = []
        self.dest = dest
        self.show("working")
        job = jobmod.Job(self.src, dest)
        threading.Thread(target=job.run, args=(self.queue.put,), daemon=True).start()
        self._after_id = self.root.after(100, self.pump)

    def pump(self):
        try:
            alive = self.root.winfo_exists()
        except tk.TclError:
            alive = False          # the interpreter itself is already gone
        if not alive:
            return
        while True:
            try:
                ev = self.queue.get_nowait()
            except queue.Empty:
                break
            kind = ev["kind"]
            if kind == "progress":
                done, total, stage = ev["done"], ev["total"], ev["stage"]
                self.bar.configure(maximum=total, value=done)
                verb = "rendering" if stage == "building slips" else "checking"
                self.progress_text.set(f"{verb} {done}/{total}")
                self.stage_text.set(f"{stage}…")
            elif kind == "log":
                self.log_lines.append(ev["line"])
                self.append_log(ev["line"])
            elif kind == "done":
                self.finish(ev["result"])
                return
        if self.state == "working":
            self._after_id = self.root.after(100, self.pump)

    def on_close(self):
        """The worker has no cancellation path, so closing mid-run leaves a
        half-written file behind. Ask first, name the file, and only ask at
        all when a run is actually in progress — the common case closes
        immediately with no dialog."""
        if self.state == "working":
            if not messagebox.askyesno(
                    "Job still running",
                    f"A packing-slip job is still running. Closing now will "
                    f"leave a half-written file at {self.dest} — do not "
                    f"print it.\n\nClose anyway?"):
                return
        if self._after_id is not None:
            self.root.after_cancel(self._after_id)
            self._after_id = None
        self.root.destroy()

    def finish(self, result):
        self.result = result
        self.tab("run")
        if result.ok:
            self.stats_text.set(f"{result.pages} pages\n{result.checks:,} checks passed")
            self.show("done")
        else:
            self.fail_text.set(result.message)
            self.mark_failure()
            self.show("failed")
        self.refresh_logs()

    def do_print(self):
        if self.result and self.result.dest:
            platform_bits.open_for_print(self.result.dest)

    def reset(self):
        self.src = self.result = None
        self.show("idle")

    def append_log(self, line):
        pass          # Task 9

def main():
    root = tk.Tk()
    app = App(root)
    if len(sys.argv) > 1:                 # dropped on the icon
        app.pick_file(sys.argv[1])
    root.mainloop()

if __name__ == "__main__":
    main()
