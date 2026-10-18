"""The window. One state at a time, three tabs, nothing else."""
import base64, datetime as dt, io, os, pathlib, queue, subprocess, sys, tempfile, threading, tkinter as tk
from tkinter import ttk, filedialog, messagebox

from PIL import Image

import branding
import dialogs
import job as jobmod
import logstore
import platform_bits
import recent
import theme
import whatnot_slips as ws

STATES = ("idle", "working", "done", "failed")

class App:
    def __init__(self, root):
        self.root = root
        root.title("Label Condense")
        root.minsize(520, 380)
        self.colors = theme.palette(root)
        self.queue = queue.Queue()
        self.state = "idle"
        self.current_tab = "run"
        self.badge_visible = False
        self.src = None
        self.result = None
        self.dest = None
        self._after_id = None
        root.protocol("WM_DELETE_WINDOW", self.on_close)

        head = ttk.Frame(root, padding=(18, 14, 18, 6)); head.pack(fill="x")
        try:
            self.header_icon = tk.PhotoImage(file=str(theme.asset("icon-32.png")))
            ttk.Label(head, image=self.header_icon).pack(side="left", padx=(0, 10))
        except tk.TclError:
            pass
        ttk.Label(head, text="Label Condense",
                  font=("TkDefaultFont", 15, "bold")).pack(side="left")

        bar = ttk.Frame(root, padding=(18, 4, 18, 10)); bar.pack(fill="x")
        tab_btn = lambda text, name: ttk.Button(
            bar, text=text, width=9, style="Toggle.TButton", command=lambda: self.tab(name))
        self.run_btn = tab_btn("Run", "run")
        self.logs_btn = tab_btn("Logs", "logs")
        self.brand_btn = tab_btn("Branding", "branding")
        self.tab_btns = {"run": self.run_btn, "logs": self.logs_btn, "branding": self.brand_btn}
        for b in self.tab_btns.values():
            b.pack(side="left", padx=(0, 6))
        self.run_btn.state(["selected"])
        ttk.Separator(root).pack(fill="x")

        self.panes = {
            "run": ttk.Frame(root),
            "logs": ttk.Frame(root),
            "branding": ttk.Frame(root),
        }
        self.frames = {name: ttk.Frame(self.panes["run"]) for name in STATES}
        self._build_idle(self.frames["idle"])
        self._build_working(self.frames["working"])
        self._build_done(self.frames["done"])
        self._build_failed(self.frames["failed"])

        self._build_branding(self.panes["branding"])
        self.panes["run"].pack(fill="both", expand=True)
        self.show("idle")

        logstore.prune(30)
        self._build_logs(self.panes["logs"])

    # ---------------------------------------------------------- navigation
    def tab(self, which):
        self.current_tab = which
        for name, pane in self.panes.items():
            pane.pack_forget()
            self.tab_btns[name].state(["selected" if name == which else "!selected"])
        self.panes[which].pack(fill="both", expand=True)
        if which == "logs":
            self.badge_visible = False
            self.logs_btn.configure(text="Logs")
            self.refresh_logs()

    def show(self, name):
        self.state = name
        for f in self.frames.values():
            f.pack_forget()
        self.frames[name].pack(fill="both", expand=True, padx=18, pady=18)
        if name == "idle":
            self.refresh_recent()
        if hasattr(self, "brand_widgets"):
            self._lock_branding(name == "working")

    def mark_failure(self):
        self.badge_visible = True
        self.logs_btn.configure(text="Logs ●")

    # ---------------------------------------------------------------- logs
    def _build_logs(self, pane):
        top = ttk.Frame(pane); top.pack(fill="x", padx=18, pady=(14, 8))
        self.picker = ttk.Combobox(top, state="readonly", values=[])
        self.picker.pack(fill="x")
        self.picker.bind("<<ComboboxSelected>>",
                         lambda e: self.select_report(self.picker.current()))

        self.logbox = tk.Text(pane, height=10, wrap="word", font=("TkFixedFont", 9),
                              **self._text_colors())
        self.logbox.pack(fill="both", expand=True, padx=18)
        self.logbox.configure(state="disabled")

        foot = ttk.Frame(pane); foot.pack(fill="x", padx=18, pady=12)
        ttk.Button(foot, text="Save report…", command=self.save_report).pack(side="right")
        ttk.Button(foot, text="Open folder",
                   command=lambda: platform_bits.reveal(logstore.log_dir())).pack(side="right", padx=6)

    def _text_colors(self):
        """tk.Text isn't a ttk widget, so the theme can't reach it."""
        c = self.colors
        return dict(background=c["field"], foreground=c["fg"], insertbackground=c["fg"],
                    relief="flat", padx=8, pady=6, highlightthickness=1,
                    highlightbackground=c["border"], highlightcolor=c["border"])

    def log_text(self):
        return self.logbox.get("1.0", "end-1c")

    def _set_log(self, text):
        self.logbox.configure(state="normal")
        self.logbox.delete("1.0", "end")
        self.logbox.insert("1.0", text)
        self.logbox.see("end")
        self.logbox.configure(state="disabled")

    def refresh_logs(self):
        self.reports = logstore.list_reports()
        labels = [logstore.label(r) for r in self.reports]
        if self.state == "working":
            labels = ["This run"] + labels
        self.picker.configure(values=labels)
        if labels:
            self.picker.current(0)
            self.select_report(0)

    def select_report(self, index):
        if index < 0:
            return
        if self.state == "working" and index == 0:
            self._set_log("\n".join(getattr(self, "log_lines", [])))
            return
        offset = 1 if self.state == "working" else 0
        r = self.reports[index - offset]
        body = r.path.read_text(encoding="utf-8").splitlines()
        if body and body[0].startswith("#meta "):
            body = body[1:]
        self._set_log("\n".join(body))

    def save_report(self):
        target = dialogs.ask_save(self.root, "Save report", pathlib.Path.home(),
                                  "label-condense-report.txt",
                                  [("Text files", "*.txt")], ".txt")
        if not target:
            return
        try:
            pathlib.Path(target).write_text(self.log_text(), encoding="utf-8")
        except OSError:
            messagebox.showerror(
                "Can't save there", f"The report could not be saved to {target}.")

    # ------------------------------------------------------------ branding
    def _build_branding(self, pane):
        saved = branding.load()
        self.form_logo = saved.logo
        f = ttk.Frame(pane); f.pack(fill="both", expand=True, padx=18, pady=16)
        f.columnconfigure(1, weight=1)

        self.brand_on = tk.BooleanVar(value=saved.enabled)
        on = ttk.Checkbutton(f, text="Show branding on slips", variable=self.brand_on,
                             style="Switch.TCheckbutton")
        on.grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 6))

        ttk.Label(f, text="Shop name").grid(row=1, column=0, sticky="w", pady=(10, 0))
        self.shop_name = tk.StringVar(value=saved.shop_name)
        name = ttk.Entry(f, textvariable=self.shop_name)
        name.grid(row=1, column=1, columnspan=2, sticky="we", padx=(12, 0), pady=(10, 0))

        ttk.Label(f, text="Logo").grid(row=2, column=0, sticky="nw", pady=(10, 0))
        self.logo_view = ttk.Label(f, text="(none — the shop name is shown)",
                                   foreground=self.colors["muted"])
        self.logo_view.grid(row=2, column=1, sticky="w", padx=(12, 0), pady=(10, 0))
        btns = ttk.Frame(f); btns.grid(row=2, column=2, sticky="ne", pady=(10, 0))
        choose = ttk.Button(btns, text="Choose…", command=self.choose_logo)
        remove = ttk.Button(btns, text="Remove", command=self.remove_logo)
        choose.pack(fill="x"); remove.pack(fill="x", pady=(4, 0))

        ttk.Label(f, text="Message").grid(row=3, column=0, sticky="nw", pady=(10, 0))
        self.message_box = tk.Text(f, height=3, width=30, wrap="word",
                                   font="TkDefaultFont", **self._text_colors())
        self.message_box.insert("1.0", saved.message)
        self.message_box.grid(row=3, column=1, columnspan=2, sticky="we",
                              padx=(12, 0), pady=(10, 0))

        self.footer_on = tk.BooleanVar(value=saved.footer_enabled)
        footer_on = ttk.Checkbutton(f, text="Show footer on slips", variable=self.footer_on,
                                    style="Switch.TCheckbutton")
        footer_on.grid(row=4, column=0, columnspan=3, sticky="w", pady=(16, 0))
        ttk.Label(f, text="Footer message").grid(row=5, column=0, sticky="nw", pady=(10, 0))
        self.footer_box = tk.Text(f, height=2, width=30, wrap="word",
                                  font="TkDefaultFont", **self._text_colors())
        self.footer_box.insert("1.0", saved.footer[:branding.FOOTER_MAX])
        self.footer_box.grid(row=5, column=1, columnspan=2, sticky="we",
                             padx=(12, 0), pady=(10, 0))
        self.footer_count = tk.StringVar(
            value=f"{len(self.footer_box.get('1.0', 'end-1c'))} / {branding.FOOTER_MAX}")
        ttk.Label(f, textvariable=self.footer_count, foreground=self.colors["muted"]
                  ).grid(row=6, column=1, columnspan=2, sticky="e", pady=(2, 0))

        foot = ttk.Frame(f); foot.grid(row=7, column=0, columnspan=3, sticky="we", pady=(18, 0))
        preview = ttk.Button(foot, text="Preview slip", command=self.preview_slip)
        preview.pack(side="left")
        self.brand_save_btn = ttk.Button(foot, text="Save", width=10, style="Accent.TButton",
                                         command=self.save_branding)
        self.brand_save_btn.pack(side="right")
        self.brand_status = tk.StringVar(value="")
        ttk.Label(foot, textvariable=self.brand_status,
                  foreground=self.colors["muted"]).pack(side="right", padx=10)

        self.brand_widgets = [on, name, choose, remove, footer_on, preview, self.brand_save_btn]
        self._show_logo()
        # a field load() had to drop would otherwise just look blank
        if saved.notes:
            self.brand_status.set("Note: " + "; ".join(saved.notes))

        unsaved = lambda *_: self.brand_status.set("Not saved yet")
        self.brand_on.trace_add("write", unsaved)
        self.shop_name.trace_add("write", unsaved)
        self.message_box.edit_modified(False)
        self.message_box.bind("<<Modified>>", self._message_edited)
        self.footer_on.trace_add("write", unsaved)
        self.footer_box.edit_modified(False)
        self.footer_box.bind("<<Modified>>", self._footer_edited)

    def _footer_edited(self, _event):
        if not self.footer_box.edit_modified():
            return
        self.footer_box.edit_modified(False)
        text = self.footer_box.get("1.0", "end-1c")
        if len(text) > branding.FOOTER_MAX:       # typed or pasted past the cap
            self.footer_box.delete(f"1.0+{branding.FOOTER_MAX}c", "end")
            text = self.footer_box.get("1.0", "end-1c")
            self.footer_box.edit_modified(False)
        self.footer_count.set(f"{len(text)} / {branding.FOOTER_MAX}")
        self.brand_status.set("Not saved yet")

    def _message_edited(self, _event):
        # Tk raises <<Modified>> only when the flag flips, so clear it each time
        if self.message_box.edit_modified():
            self.brand_status.set("Not saved yet")
            self.message_box.edit_modified(False)

    def _lock_branding(self, locked):
        """Settings are read once when a run starts; editing mid-run would
        look like it applied when it didn't."""
        for w in self.brand_widgets:
            w.state(["disabled"] if locked else ["!disabled"])
        self.message_box.configure(state="disabled" if locked else "normal")
        self.footer_box.configure(state="disabled" if locked else "normal")

    def _show_logo(self):
        if self.form_logo is None:
            self.logo_photo = None
            self.logo_view.configure(image="", text="(none — the shop name is shown)")
            return
        im = self.form_logo.resize((self.form_logo.width // 2,
                                    max(1, self.form_logo.height // 2)), Image.NEAREST)
        buf = io.BytesIO(); im.save(buf, "PNG")
        self.logo_photo = tk.PhotoImage(data=base64.b64encode(buf.getvalue()))
        self.logo_view.configure(image=self.logo_photo, text="")

    def form_brand(self):
        return branding.Brand(enabled=self.brand_on.get(),
                              shop_name=self.shop_name.get().strip(),
                              message=self.message_box.get("1.0", "end-1c").strip(),
                              logo=self.form_logo,
                              footer_enabled=self.footer_on.get(),
                              footer=self.footer_box.get("1.0", "end-1c").strip())

    def choose_logo(self, path=None):
        if path is None:
            path = dialogs.ask_open(
                self.root, "Choose your logo", pathlib.Path.home(),
                [("Images", "*.png *.jpg *.jpeg *.gif *.bmp *.webp"), ("All files", "*")])
        if not path:
            return
        try:
            self.form_logo = branding.import_logo(path)
        # not just OSError/ValueError: Pillow also raises DecompressionBombError,
        # MemoryError and others, and any of them would surface as a traceback
        except Exception as exc:
            messagebox.showerror("Can't use that image", str(exc))
            return
        self.brand_status.set("Not saved yet")
        self._show_logo()

    def remove_logo(self):
        self.form_logo = None
        self.brand_status.set("Not saved yet")
        self._show_logo()

    def save_branding(self):
        b = self.form_brand()
        errs = branding.problems(b)
        if errs:
            messagebox.showerror("Can't save", "\n".join(errs))
            return False
        try:
            branding.save(b)
        except OSError as exc:
            messagebox.showerror("Can't save", f"The settings could not be saved: {exc}")
            return False
        self.brand_status.set("Saved")
        return True

    def preview_slip(self):
        b = self.form_brand()
        errs = branding.problems(b)
        if errs:
            messagebox.showerror("Can't preview", "\n".join(errs))
            return
        with tempfile.TemporaryDirectory() as td:
            png = pathlib.Path(td) / "preview.png"
            try:
                ws.preview_png(b if b.enabled else None, png,
                               footer=b.footer if b.footer_enabled else None,
                               prices=self.show_prices.get())
            except (OSError, subprocess.CalledProcessError) as exc:
                messagebox.showerror("Can't preview", f"The preview could not be drawn: {exc}")
                return
            photo = tk.PhotoImage(file=str(png)).subsample(2)
        win = tk.Toplevel(self.root); win.title("Slip preview")
        lbl = ttk.Label(win, image=photo); lbl.image = photo
        lbl.pack(padx=8, pady=8)

    # ---------------------------------------------------------------- idle
    def _build_idle(self, f):
        card = ttk.Frame(f, style="Card.TFrame", padding=30)
        card.pack(fill="both", expand=True)
        ttk.Label(card, text="Choose a Whatnot export",
                  font=("TkDefaultFont", 14, "bold")).pack(pady=(14, 6))
        ttk.Label(card, text="Combined Labels + Packing Slips, straight from Whatnot.",
                  foreground=self.colors["muted"]).pack()
        ttk.Button(card, text="Choose file…", width=16, style="Accent.TButton",
                   command=self.pick_file).pack(pady=(18, 4), ipady=3)
        self.show_prices = tk.BooleanVar(value=recent.get_pref("show_prices", True))
        self.pick_list = tk.BooleanVar(value=recent.get_pref("pick_list", False))
        self.show_prices.trace_add(
            "write", lambda *_: recent.set_pref("show_prices", self.show_prices.get()))
        self.pick_list.trace_add(
            "write", lambda *_: recent.set_pref("pick_list", self.pick_list.get()))
        opts = ttk.Frame(card); opts.pack(pady=(6, 0))
        ttk.Checkbutton(opts, text="Show prices", variable=self.show_prices).pack(anchor="w")
        ttk.Checkbutton(opts, text="Add pick list", variable=self.pick_list).pack(anchor="w")
        # one click for the export that just landed in Downloads
        row = ttk.Frame(card); row.pack()
        self.recent_btn = ttk.Button(row, command=self.use_recent)
        self.recent_note = ttk.Label(row, foreground=self.colors["muted"])
        self.recent_path = None
        ttk.Label(card, text="You can also drop an export on the app's icon.",
                  foreground=self.colors["muted"]).pack(side="bottom")
        self.root.bind("<FocusIn>", self._focus_in, add="+")

    def _focus_in(self, event):
        if event.widget is self.root and self.state == "idle":
            self.refresh_recent()

    def refresh_recent(self):
        """Offer the newest Whatnot export, or nothing. The folder is re-read
        each time the window comes forward, so a fresh download shows up."""
        found = recent.newest_export()
        self.recent_path = found[0] if found else None
        if not found:
            self.recent_btn.pack_forget(); self.recent_note.pack_forget()
            return
        path, when = found
        self.recent_btn.configure(text=f"Use {recent.short(path.name)}")
        self.recent_note.configure(text=f"Newest in {path.parent.name} · {recent.age(when)}")
        self.recent_btn.pack(pady=(10, 2)); self.recent_note.pack()

    def use_recent(self):
        if self.recent_path is not None:
            self.pick_file(str(self.recent_path))

    def pick_file(self, path=None):
        if path is None:
            path = dialogs.ask_open(self.root, "Choose a Whatnot export", recent.export_dir(),
                                    [("PDF files", "*.pdf *.PDF"), ("All files", "*")])
        if not path:
            return
        self.src = pathlib.Path(path)
        recent.remember_folder(self.src)
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
                  foreground=self.colors["muted"]).pack(pady=(10, 2))
        ttk.Label(f, textvariable=self.stage_text, foreground=self.colors["muted"]).pack()

    def _build_done(self, f):
        self.stats_text = tk.StringVar(value="")
        ttk.Label(f, text="✓  Ready to print", foreground=self.colors["ok"],
                  font=("TkDefaultFont", 13, "bold")).pack(pady=(26, 10))
        ttk.Label(f, textvariable=self.stats_text, foreground=self.colors["muted"],
                  justify="center").pack()
        row = ttk.Frame(f); row.pack(pady=16)
        ttk.Button(row, text="Print", width=10, style="Accent.TButton",
                   command=self.do_print).pack(side="left", padx=5)
        ttk.Button(row, text="Do another", command=self.reset).pack(side="left", padx=5)
        ttk.Button(f, text="See the full report",
                   command=lambda: self.tab("logs")).pack()

    def _build_failed(self, f):
        self.fail_text = tk.StringVar(value="")
        ttk.Label(f, text="✗  DO NOT PRINT", foreground=self.colors["bad"],
                  font=("TkDefaultFont", 13, "bold")).pack(pady=(26, 10))
        ttk.Label(f, text="This export failed its checks. Nothing was saved.",
                  justify="center").pack()
        ttk.Label(f, textvariable=self.fail_text, foreground=self.colors["muted"]).pack(pady=(6, 0))
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
            # beside the export, which is where the user just was
            folder = self.src.parent if self.src else recent.export_dir()
            dest = dialogs.ask_save(self.root, "Save print-ready PDF as…", folder,
                                    self.default_name(), [("PDF files", "*.pdf")], ".pdf")
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
        job = jobmod.Job(self.src, dest, brand=branding.active(),
                           footer=branding.active_footer(),
                           prices=self.show_prices.get(), pick_list=self.pick_list.get())
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
        self.logbox.configure(state="normal")
        self.logbox.insert("end", line + "\n")
        self.logbox.see("end")
        self.logbox.configure(state="disabled")

    def maybe_offer_desktop_entry(self):
        if not platform_bits.should_offer_desktop_entry():
            return
        yes = messagebox.askyesno(
            "Add to your applications menu?",
            "Add Label Condense to your applications menu, so you can find it "
            "without hunting for this file?\n\nYou'll only be asked once.")
        try:
            if yes:
                platform_bits.install_desktop_entry(sys.executable, theme.asset("icon-256.png"))
            else:
                platform_bits.remember_desktop_choice(False)
        except OSError:
            if not yes:
                # User declined, remember failed. Accept it silently; will ask again next time.
                return
            # User accepted, install failed. Try to mark "already asked" so we don't keep nagging.
            try:
                platform_bits.remember_desktop_choice(False)
                msg = "It will not ask again."
            except OSError:
                msg = "You can try again later."
            messagebox.showerror(
                "Could not add menu entry",
                f"The application menu entry could not be created, but Label Condense works normally. {msg}")

def main():
    if sys.argv[1:] == ["--selftest"]:
        # No export to hand (CI): prove the bundled gs starts and renders.
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            png = pathlib.Path(td) / "preview.png"
            ws.preview_png(branding.Brand(enabled=True, shop_name="Selftest"), png)
            print(f"selftest: preview ok ({png.stat().st_size} bytes)")
        missing = [n for n in ("sv/sv.tcl", "icon-256.png", "icon-32.png")
                   if not theme.asset(n).is_file()]
        if missing:
            print(f"selftest: missing assets {missing}")
            sys.exit(1)
        print("selftest: theme and icons present")
        sys.exit(0)
    if len(sys.argv) > 2 and sys.argv[1] == "--selftest":
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            out = pathlib.Path(td) / "out.pdf"
            res = jobmod.Job(sys.argv[2], out, deep=False).run(lambda e: None)
        print(f"selftest: ok={res.ok} checks={res.checks} failures={res.failures}")
        sys.exit(0 if res.ok else 1)

    root = tk.Tk()
    theme.apply(root)
    app = App(root)
    app.maybe_offer_desktop_entry()
    if sys.platform == "darwin":          # dropped on the Dock or Finder icon
        root.createcommand("::tk::mac::OpenDocument",
                           lambda *paths: app.pick_file(paths[0]))
    if len(sys.argv) > 1:                 # dropped on the icon
        app.pick_file(sys.argv[1])
    root.mainloop()

if __name__ == "__main__":
    main()
