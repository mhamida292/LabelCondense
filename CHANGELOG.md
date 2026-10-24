# Changelog

Each release's section becomes the "What's new" part of its notes on the
Releases page. The release build refuses a tag that has no section here.

## v1.8.0

- **TikTok Shop exports.** Drop a TikTok label + packing slip PDF in, the
  same as a Whatnot one; the app tells which it is and says so. A live
  auction's lot numbers become `#N`, so a buyer's repeat wins collapse onto
  one line with every number and price under it. The slip keeps TikTok's
  order ID, dates, tracking number, show name and buyer, and every fact is
  checked against the original export.
- **TikTok pick list.** Add pick list on a TikTok export lists every lot in
  order with the buyer's nickname, grouped by show.
- **Condense repeated items.** A new switch on the Run tab, on by default.
  Turn it off to give every item its own row. `./run.sh --no-condense` does
  the same.
- TikTok labels are cut out of their A6 page and scaled evenly to 4×6, so
  the barcode is never stretched.

## v1.7.0

- **Footer message.** The Branding tab has a new Footer message: up to 2
  lines and 120 characters at the bottom of every slip, with its own Show
  footer on slips switch so it can be on without the header message.
- **Show prices.** A switch on the Run tab. Turn it off to print slips with
  no prices. The check confirms no dollar amount is left on any slip.
- **Add pick list.** A switch on the Run tab that puts a pick list at the
  front of the PDF: each product once, with the quantity to pull. The
  quantities are checked against the original export.
- **Message counter.** The header message box now counts as you type and
  stops at 60 characters, like the footer's.

## v1.6.0

- **One-click exports.** When a Whatnot export has arrived in Downloads in
  the past week, the Run tab offers it as a button: click it instead of
  browsing. Renamed files aren't offered; use Choose file… for those.
- **Better file picker on Linux.** Choose file… opens your desktop's own
  picker (KDE's or GNOME's) with Places, Recent and search, instead of Tk's
  plain one.
- **Opens where your exports are.** The picker starts in Downloads, then in
  the last folder you used, and the finished PDF is saved beside the export
  by default.
- The Run tab no longer says "drop here", since drops only work on the app's
  icon.

## v1.5.0

- **New look.** A cleaner, modern window on Windows, Mac and Linux: a header
  with the app's name, tabs that show which one you're on, and the main
  button on each screen in teal. It follows your computer's light or dark
  setting.
- **App icon.** Label Condense has its own icon in the taskbar, Dock, title
  bar and app menu.

## v1.4.0

- **Giveaways stand out.** On any item whose name starts with GIVEAWAY, the
  word prints white on a black box, so a free item is hard to miss while
  packing.
- **Branding preview uses sample items.** Preview slip shows made-up
  products instead of real ones from your listings.

## v1.3.0

- **Mac version.** A download for Apple Silicon Macs (M1 or newer, macOS
  14.8+). Like the other versions, it carries its own Ghostscript and
  Poppler, so there's nothing to install.

## v1.2.0

- **SKUs on slips.** Items that have a SKU print it before the name, like
  `[TB200-477] CRUNCHY LOBSTER`, for picking from the shelf. The audit checks
  every SKU against the export, so a missing, extra, or swapped SKU blocks
  the run.
- **Fixed:** SKU text no longer leaks into product names (such as
  `JUMBO CRUNCHY STRAWBERRY DUCK SKU ZW-112B #1`).
- **Branding tab.** Put your shop name or logo and a thank-you message at
  the top of every slip. Preview slip shows exactly what prints. It's off
  until you turn it on and Save.
- **Labels are rendered, not extracted,** and international tracking numbers
  are accepted.
