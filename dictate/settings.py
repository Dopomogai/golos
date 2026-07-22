"""Menu-bar status item and the Settings window (History / General / Prompt /
Learning / Dictionary).

History is the first tab and the default home surface. The remaining tabs keep
the same controls and selectors as before, laid out with clearer hierarchy,
section cards, and system semantic colors (dark/light compatible).

The app stays NSApplicationActivationPolicyAccessory: opening Settings calls
NSApp.activateIgnoringOtherApps_(True) and makeKeyAndOrderFront; closing the
window lets the accessory app fall back to the background on its own.

ObjC classes are defined lazily inside factory functions so importing this
module headless is safe. PyObjC note: ObjC subclasses must use objc.super,
not Python super.
"""

import json
import logging
import threading
from pathlib import Path

log = logging.getLogger(__name__)

WINDOW_W, WINDOW_H = 620.0, 680.0
LATEST_RELEASE_URL = "https://github.com/Dopomogai/golos/releases/latest"

# ObjC class names are process-global: define each exactly once.
_class_cache: dict = {}


def _trunc(s: str, n: int = 24) -> str:
    """Ellipsize for menu/bubble labels; keeps UI rows a fixed visual width."""
    return s if len(s) <= n else s[:n - 1] + "…"


def _load_glyph_image():
    """The chakra menu-bar glyph as a template image (bundle resource when
    frozen, assets/ in dev). None if the file is missing."""
    from pathlib import Path
    from AppKit import NSImage, NSBundle
    from .config import PROJECT_ROOT
    candidates = []
    try:
        res = NSBundle.mainBundle().pathForResource_ofType_("glyph", "png")
        if res:
            candidates.append(str(res))
    except Exception:
        pass
    candidates.append(str(PROJECT_ROOT / "assets" / "glyph.png"))
    for path in candidates:
        if Path(path).exists():
            img = NSImage.alloc().initWithContentsOfFile_(path)
            if img is not None:
                img.setTemplate_(True)  # alpha-driven; auto light/dark
                img.setSize_((14.0, 14.0))  # middle ground: 18pt was too big, 11pt too small
                return img
    return None


# ---------------------------------------------------------------------------
# status item


def build_status_item(on_settings, on_reload=None, on_onboarding=None,
                      on_notice=None):
    """Create the menu-bar status item. Returns (item, target) — keep both alive."""
    import objc
    from AppKit import (
        NSStatusBar, NSMenu, NSMenuItem, NSImage, NSVariableStatusItemLength,
    )
    from Foundation import NSObject

    if "MenuTarget" not in _class_cache:
        class MenuTarget(NSObject):
            def initWithCallback_(self, cb):
                self = objc.super(MenuTarget, self).init()
                if self is None:
                    return None
                self._cb = cb
                self._cb_onboarding = None
                self._on_notice = None
                self._on_reload = None
                return self

            def openSettings_(self, sender):
                self._cb()

            def openOnboarding_(self, sender):
                if self._cb_onboarding:
                    self._cb_onboarding()

            def checkForUpdates_(self, sender):
                """Open the canonical release channel; unsigned betas update manually."""
                from AppKit import NSWorkspace
                from Foundation import NSURL
                NSWorkspace.sharedWorkspace().openURL_(
                    NSURL.URLWithString_(LATEST_RELEASE_URL))

            def testInsertion_(self, sender):
                from .insert import insert_text
                ok = insert_text("✅ golos insertion test")
                if self._on_notice:
                    if ok:
                        self._on_notice("test insertion posted", "success")
                    else:
                        self._on_notice(
                            "Accessibility needed — open Permissions", "warn")

            def exportDiagnostics_(self, sender):
                """User-selected, redacted local support bundle; never uploads."""
                from AppKit import NSSavePanel, NSModalResponseOK, NSWorkspace
                from Foundation import NSURL
                from .diagnostics import create_support_bundle, default_bundle_name
                panel = NSSavePanel.savePanel()
                panel.setNameFieldStringValue_(default_bundle_name())
                panel.setCanCreateDirectories_(True)
                panel.setPrompt_("Export")
                if panel.runModal() != NSModalResponseOK:
                    return
                try:
                    path = create_support_bundle(Path(panel.URL().path()))
                    NSWorkspace.sharedWorkspace().activateFileViewerSelectingURLs_(
                        [NSURL.fileURLWithPath_(str(path))])
                    if self._on_notice:
                        self._on_notice("diagnostics exported", "success")
                except Exception as exc:
                    log.exception("Diagnostics export failed: %s", exc)
                    if self._on_notice:
                        self._on_notice("diagnostics export failed", "warn")

            def addSelectionToDictionary_(self, sender):
                from .learning import read_selection, promote_to_dictionary
                from .config import load_config
                text = read_selection()
                if not text:
                    log.info("Add selection to dictionary: no selection readable "
                             "(nothing selected, or Accessibility not granted).")
                    if self._on_notice:
                        self._on_notice("no text selected", "warn")
                    return
                path = load_config()["paths"]["dictionary"]
                # take a single line — dictionary.txt is one term per line
                term = " ".join(text.split())[:120]
                promote_to_dictionary(path, term)
                if self._on_reload:
                    self._on_reload()
                if self._on_notice:
                    self._on_notice(f'✓ "{_trunc(term)}" in dictionary', "success")

            def openPermissionPage_(self, sender):
                from .permissions import open_settings_page
                open_settings_page(sender.representedObject())

            def menuNeedsUpdate_(self, menu):
                # Refresh the ✓/✗ permission items each time the menu opens.
                from .permissions import check_all, granted, TITLES
                status = check_all()
                for item in menu.itemArray():
                    kind = item.representedObject()
                    if kind in status:
                        mark = "✓" if granted(status[kind]) else "✗"
                        suffix = "" if granted(status[kind]) else " — click to open Settings"
                        item.setTitle_(f"{mark} {TITLES[kind]}{suffix}")

        _class_cache["MenuTarget"] = MenuTarget
    MenuTarget = _class_cache["MenuTarget"]

    target = MenuTarget.alloc().initWithCallback_(on_settings)
    target._on_reload = on_reload
    target._cb_onboarding = on_onboarding
    target._on_notice = on_notice
    item = NSStatusBar.systemStatusBar().statusItemWithLength_(
        NSVariableStatusItemLength)
    img = _load_glyph_image()
    if img is not None:
        item.button().setImage_(img)
    else:
        sym = NSImage.imageWithSystemSymbolName_accessibilityDescription_(
            "mic.fill", "golos")
        if sym is not None:
            item.button().setImage_(sym)
        else:
            item.button().setTitle_("◉")
    item.button().setToolTip_("golos — hold fn to dictate")

    menu = NSMenu.alloc().init()
    menu.setDelegate_(target)  # menuNeedsUpdate: refreshes permission ✓/✗ marks

    settings_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
        "Settings…", "openSettings:", "")
    settings_item.setTarget_(target)
    menu.addItem_(settings_item)

    ob_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
        "Welcome / Setup…", "openOnboarding:", "")
    ob_item.setTarget_(target)
    menu.addItem_(ob_item)

    update_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
        "Check for Updates…", "checkForUpdates:", "")
    update_item.setTarget_(target)
    menu.addItem_(update_item)

    test_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
        "Test insertion", "testInsertion:", "")
    test_item.setTarget_(target)
    menu.addItem_(test_item)

    sel_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
        "Add selection to dictionary", "addSelectionToDictionary:", "")
    sel_item.setTarget_(target)
    menu.addItem_(sel_item)

    # Permissions submenu: one ✓/✗ item per permission; ✗ items open the
    # corresponding System Settings pane when clicked.
    from .permissions import check_all, granted, TITLES
    perm_status = check_all()
    perm_menu = NSMenu.alloc().init()
    perm_menu.setDelegate_(target)  # refresh ✓/✗ when the submenu opens
    for kind in ("accessibility", "input_monitoring", "microphone"):
        ok = granted(perm_status[kind])
        mark = "✓" if ok else "✗"
        suffix = "" if ok else " — click to open Settings"
        entry = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            f"{mark} {TITLES[kind]}{suffix}", "openPermissionPage:", "")
        entry.setTarget_(target)
        entry.setRepresentedObject_(kind)
        perm_menu.addItem_(entry)
    perm_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
        "Permissions", "", "")
    perm_item.setSubmenu_(perm_menu)
    menu.addItem_(perm_item)

    diagnostics_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
        "Export Diagnostics…", "exportDiagnostics:", "")
    diagnostics_item.setTarget_(target)
    menu.addItem_(diagnostics_item)

    menu.addItem_(NSMenuItem.separatorItem())
    # nil target -> terminate: travels the responder chain to NSApplication
    menu.addItem_(NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
        "Quit", "terminate:", ""))
    item.setMenu_(menu)
    return item, target


# ---------------------------------------------------------------------------
# settings window


def build_settings_window(app_controller):
    """Create (hidden) the settings window; returns a controller with .show().

    Must be called at most once per process: it defines the SettingsController
    ObjC class inline (ObjC class names are process-global). AppController
    keeps the result as a singleton, so this holds by construction.
    """
    import objc
    from AppKit import (
        NSApp, NSWindow, NSTabView, NSTabViewItem, NSView, NSTextField,
        NSPopUpButton, NSComboBox, NSSecureTextField, NSButton, NSScrollView,
        NSTextView, NSTableView, NSTableColumn, NSFont, NSColor, NSBox, NSSlider,
        NSWindowStyleMaskTitled, NSWindowStyleMaskClosable,
        NSBackingStoreBuffered, NSMakeRect, NSViewWidthSizable,
    )
    from Foundation import NSObject, NSIndexSet
    from PyObjCTools import AppHelper

    from .config import update_config
    from .openrouter import (
        DEFAULT_CHAT_MODEL, DEFAULT_STT_MODEL, audio_model_ids, fetch_models,
        get_api_key, text_model_ids, transcription_model_ids,
    )

    # Usable height inside a tab's content view (tab bar eats ~36–40 pt).
    CONTENT_H = WINDOW_H - 56
    CONTENT_W = WINDOW_W - 20
    INSET = 16.0
    INNER_W = CONTENT_W - INSET * 2
    # Brand accent (onboarding orange) — primary actions only.
    ACCENT = NSColor.colorWithCalibratedRed_green_blue_alpha_(1.0, 0.45, 0.15, 1.0)

    def make_label(text, x, y, w=150, h=18, size=13, bold=False, color=None,
                   selectable=False):
        tf = NSTextField.alloc().initWithFrame_(NSMakeRect(x, y, w, h))
        tf.setStringValue_(text)
        tf.setBezeled_(False)
        tf.setDrawsBackground_(False)
        tf.setEditable_(False)
        tf.setSelectable_(selectable)
        tf.setFont_(NSFont.boldSystemFontOfSize_(size) if bold
                    else NSFont.systemFontOfSize_(size))
        tf.setTextColor_(color if color is not None else NSColor.labelColor())
        return tf

    def make_title(text, x, y, w=400, h=22):
        """Primary section / page title."""
        return make_label(text, x, y, w=w, h=h, size=15, bold=True)

    def make_subtitle(text, x, y, w=500, h=16):
        """Secondary help under a title."""
        return make_label(text, x, y, w=w, h=h, size=11, bold=False,
                          color=NSColor.secondaryLabelColor())

    def make_section_label(text, x, y, w=400, h=16):
        """Small caps-style section heading inside a tab."""
        return make_label(text, x, y, w=w, h=h, size=11, bold=True,
                          color=NSColor.secondaryLabelColor())

    def make_hint(text, x, y, w=500, h=14, size=11):
        return make_label(text, x, y, w=w, h=h, size=size, bold=False,
                          color=NSColor.secondaryLabelColor())

    def make_card(parent, x, y, w, h):
        """Rounded section background using system colors (dark/light safe)."""
        box = NSBox.alloc().initWithFrame_(NSMakeRect(x, y, w, h))
        box.setTitle_("")
        box.setTitlePosition_(0)  # NSNoTitle
        box.setBoxType_(4)  # NSBoxCustom
        box.setCornerRadius_(10.0)
        box.setBorderWidth_(1.0)
        box.setBorderColor_(NSColor.separatorColor())
        box.setFillColor_(NSColor.controlBackgroundColor())
        box.setContentViewMargins_((0.0, 0.0))
        parent.addSubview_(box)
        return box

    def make_accent_bar(parent, x, y, h=18):
        """Thin brand accent strip — restrained, decorative only."""
        bar = NSBox.alloc().initWithFrame_(NSMakeRect(x, y, 3.0, h))
        bar.setTitle_("")
        bar.setTitlePosition_(0)
        bar.setBoxType_(4)  # NSBoxCustom
        bar.setBorderWidth_(0.0)
        bar.setFillColor_(ACCENT)
        bar.setCornerRadius_(1.5)
        bar.setContentViewMargins_((0.0, 0.0))
        parent.addSubview_(bar)
        return bar

    def make_button(title, x, y, w, h=28, action=None, target=None, primary=False):
        btn = NSButton.alloc().initWithFrame_(NSMakeRect(x, y, w, h))
        btn.setTitle_(title)
        btn.setBezelStyle_(1)  # NSBezelStyleRounded
        if primary:
            try:
                btn.setKeyEquivalent_("\r")
            except Exception:
                pass
        if target is not None and action is not None:
            btn.setTarget_(target)
            btn.setAction_(action)
        return btn

    def make_text_scroll(x, y, w, h, editable=True, font_size=12):
        scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(x, y, w, h))
        scroll.setHasVerticalScroller_(True)
        scroll.setBorderType_(1)  # NSLineBorder
        scroll.setDrawsBackground_(True)
        tv = NSTextView.alloc().initWithFrame_(
            NSMakeRect(0, 0, scroll.contentSize().width, scroll.contentSize().height))
        tv.setRichText_(False)
        tv.setFont_(NSFont.fontWithName_size_("Menlo", font_size)
                    or NSFont.userFixedPitchFontOfSize_(font_size))
        tv.setEditable_(editable)
        tv.setAutoresizingMask_(NSViewWidthSizable)
        # Readable in both appearances via text/background system colors.
        try:
            tv.setTextColor_(NSColor.textColor())
            tv.setBackgroundColor_(NSColor.textBackgroundColor())
        except Exception:
            pass
        scroll.setDocumentView_(tv)
        return scroll, tv

    def style_table(table):
        table.setUsesAlternatingRowBackgroundColors_(True)
        table.setRowHeight_(22.0)
        table.setGridStyleMask_(0)  # no grid — cleaner with alternating rows
        try:
            table.setSelectionHighlightStyle_(1)  # regular
        except Exception:
            pass

    class SettingsController(NSObject):
        def initWithAppController_(self, ctl):
            self = objc.super(SettingsController, self).init()
            if self is None:
                return None
            self.app_controller = ctl
            self._records = []
            self._suggestions = []
            self._terms = []
            self._corrections = []
            self._build_window()
            self._load_general()
            self._load_prompt()
            self._load_learning()
            self._load_dictionary_files()
            self._load_history()
            self._load_suggestions()
            return self

        # -- construction --------------------------------------------------

        def _build_window(self):
            self.window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
                NSMakeRect(200, 200, WINDOW_W, WINDOW_H),
                NSWindowStyleMaskTitled | NSWindowStyleMaskClosable,
                NSBackingStoreBuffered, False)
            self.window.setTitle_("golos Settings")
            self.window.setDelegate_(self)
            self.window.setReleasedWhenClosed_(False)
            try:
                self.window.setBackgroundColor_(NSColor.windowBackgroundColor())
            except Exception:
                pass

            tabs = NSTabView.alloc().initWithFrame_(
                NSMakeRect(8, 8, WINDOW_W - 16, WINDOW_H - 16))
            self.window.contentView().addSubview_(tabs)
            self.tabs = tabs
            # History first — app home / dashboard.
            self._build_history_tab(tabs)
            self._build_general_tab(tabs)
            self._build_prompt_tab(tabs)
            self._build_learning_tab(tabs)
            self._build_dictionary_tab(tabs)
            tabs.selectFirstTabViewItem_(None)

        _CONTEXT_TOGGLES = (
            ("enabled", "Context providers (master switch)"),
            ("app_info", "Frontmost app & window title"),
            ("text_before_cursor", "Text before cursor (input field)"),
            ("focused_field_text", "Focused field text (full input)"),
            ("visible_text", "Surrounding on-screen text (citations)"),
            ("browser", "Browser page (title & URL)"),
            ("vscode", "VS Code workspace files"),
            ("finder", "Finder selection & window"),
        )

        def _build_history_tab(self, tabs):
            """Home dashboard: recent dictations, detail, and edit suggestions."""
            v = NSView.alloc().initWithFrame_(
                NSMakeRect(0, 0, CONTENT_W, CONTENT_H))

            # Header
            make_accent_bar(v, INSET, CONTENT_H - 36, h=20)
            v.addSubview_(make_title("Recent dictations", INSET + 10, CONTENT_H - 38, w=280))
            self.history_count_label = make_subtitle(
                "Local log of every transcription on this Mac.",
                INSET + 10, CONTENT_H - 56, w=360)
            v.addSubview_(self.history_count_label)

            cbtn = make_button("Check for edits", CONTENT_W - INSET - 240,
                               CONTENT_H - 42, 130, 28,
                               "checkForEdits:", self)
            v.addSubview_(cbtn)
            rbtn = make_button("Refresh", CONTENT_W - INSET - 100,
                               CONTENT_H - 42, 100, 28,
                               "refreshHistory:", self)
            v.addSubview_(rbtn)

            # Bottom-up layout so actions never collide with tables.
            btn_y = 12.0
            sug_h = 72.0
            sug_y = btn_y + 34.0
            sug_label_y = sug_y + sug_h + 6.0
            detail_h = 92.0
            detail_y = sug_label_y + 20.0
            detail_label_y = detail_y + detail_h + 6.0
            table_top = CONTENT_H - 68.0
            table_y = detail_label_y + 20.0
            table_h = max(140.0, table_top - table_y)

            # History table card
            make_card(v, INSET - 4, table_y - 6, INNER_W + 8, table_h + 12)

            scroll = NSScrollView.alloc().initWithFrame_(
                NSMakeRect(INSET, table_y, INNER_W, table_h))
            scroll.setHasVerticalScroller_(True)
            scroll.setBorderType_(0)  # borderless inside card
            scroll.setDrawsBackground_(False)
            self.table = NSTableView.alloc().initWithFrame_(scroll.bounds())
            for ident, title, width in (("time", "Time", 128),
                                        ("app", "App", 110),
                                        ("text", "Raw → Final", 300)):
                col = NSTableColumn.alloc().initWithIdentifier_(ident)
                col.headerCell().setStringValue_(title)
                col.setWidth_(width)
                col.setMinWidth_(60)
                self.table.addTableColumn_(col)
            # Raw → Final soaks up extra width; columns stay user-resizable.
            self.table.setColumnAutoresizingStyle_(4)  # last column only
            self.table.setDataSource_(self)
            self.table.setDelegate_(self)
            style_table(self.table)
            self.table.setRowHeight_(24.0)
            scroll.setDocumentView_(self.table)
            v.addSubview_(scroll)

            # Detail card
            v.addSubview_(make_section_label(
                "SELECTED DICTATION", INSET, detail_label_y, w=280))
            self.history_action_status = make_hint(
                "", INSET + 142, detail_label_y, w=140, h=16, size=10)
            v.addSubview_(self.history_action_status)
            copy_btn = make_button(
                "Copy text", CONTENT_W - INSET - 284,
                detail_label_y - 5, 88, 24, "copyHistoryText:", self)
            v.addSubview_(copy_btn)
            self.retry_history_button = make_button(
                "Retry", CONTENT_W - INSET - 188,
                detail_label_y - 5, 84, 24, "retryHistory:", self)
            v.addSubview_(self.retry_history_button)
            audio_btn = make_button(
                "Show audio", CONTENT_W - INSET - 96,
                detail_label_y - 5, 96, 24, "showHistoryAudio:", self)
            v.addSubview_(audio_btn)
            make_card(v, INSET - 4, detail_y - 4, INNER_W + 8, detail_h + 8)
            dscroll, self.detail_text = make_text_scroll(
                INSET, detail_y, INNER_W, detail_h,
                editable=False, font_size=11)
            dscroll.setBorderType_(0)
            v.addSubview_(dscroll)
            self.detail_text.setString_(
                "Select a row above to inspect raw text, final insert, and context.")

            # Suggestions card
            v.addSubview_(make_section_label(
                "SUGGESTIONS FROM YOUR EDITS", INSET, sug_label_y, w=360))
            make_card(v, INSET - 4, sug_y - 4, INNER_W + 8, sug_h + 8)

            sscroll = NSScrollView.alloc().initWithFrame_(
                NSMakeRect(INSET, sug_y, INNER_W, sug_h))
            sscroll.setHasVerticalScroller_(True)
            sscroll.setBorderType_(0)
            sscroll.setDrawsBackground_(False)
            self.sug_table = NSTableView.alloc().initWithFrame_(sscroll.bounds())
            for ident, title, width in (("wrong", "Wrong", 190),
                                        ("right", "Right", 190),
                                        ("count", "×", 36),
                                        ("app", "Last app", 100)):
                col = NSTableColumn.alloc().initWithIdentifier_(ident)
                col.headerCell().setStringValue_(title)
                col.setWidth_(width)
                self.sug_table.addTableColumn_(col)
            self.sug_table.setDataSource_(self)
            self.sug_table.setDelegate_(self)
            style_table(self.sug_table)
            sscroll.setDocumentView_(self.sug_table)
            v.addSubview_(sscroll)

            # Promote / dismiss actions
            for title, action, x in (
                    ("Add to corrections", "addToCorrections:", INSET),
                    ("Add to dictionary", "addToDictionary:", INSET + 150),
                    ("Dismiss", "dismissSuggestion:", INSET + 300)):
                btn = make_button(title, x, btn_y, 140, 28, action, self)
                v.addSubview_(btn)

            item = NSTabViewItem.alloc().initWithIdentifier_("history")
            item.setLabel_("History")
            item.setView_(v)
            tabs.addTabViewItem_(item)

        def _build_prompt_tab(self, tabs):
            v = NSView.alloc().initWithFrame_(
                NSMakeRect(0, 0, CONTENT_W, CONTENT_H))

            make_accent_bar(v, INSET, CONTENT_H - 34, h=18)
            v.addSubview_(make_title(
                "Prompt & context", INSET + 10, CONTENT_H - 36, w=320))
            v.addSubview_(make_subtitle(
                "What the formatting model may see, and the system prompt template.",
                INSET + 10, CONTENT_H - 54, w=560))

            # Context toggles card
            ctx_card_h = 148
            ctx_card_y = CONTENT_H - 68 - ctx_card_h
            make_card(v, INSET - 4, ctx_card_y, INNER_W + 8, ctx_card_h)
            v.addSubview_(make_section_label(
                "SHARE WITH THE FORMATTING MODEL",
                INSET + 8, CONTENT_H - 86, w=360))

            self._ctx_boxes = {}
            for i, (key, title) in enumerate(self._CONTEXT_TOGGLES):
                col, row = divmod(i, 4)
                cb = NSButton.alloc().initWithFrame_(
                    NSMakeRect(INSET + 8 + col * 290,
                               CONTENT_H - 112 - row * 24, 280, 22))
                cb.setButtonType_(3)  # NSSwitchButton
                cb.setTitle_(title)
                cb.setState_(1)
                v.addSubview_(cb)
                self._ctx_boxes[key] = cb

            v.addSubview_(make_hint(
                "Off = never read, never leaves this Mac.",
                INSET + 8, ctx_card_y + 8, w=500, h=14, size=10))

            # Formatter options card
            opt_y = ctx_card_y - 96
            make_card(v, INSET - 4, opt_y, INNER_W + 8, 88)
            self.answer_checkbox = NSButton.alloc().initWithFrame_(
                NSMakeRect(INSET + 8, opt_y + 56, 520, 22))
            self.answer_checkbox.setButtonType_(3)
            self.answer_checkbox.setTitle_(
                "Answer obvious questions from context (instead of transcribing)")
            v.addSubview_(self.answer_checkbox)
            v.addSubview_(make_hint(
                "Off = always transcribe exactly what you said.",
                INSET + 28, opt_y + 40, w=500, h=14, size=10))

            self.audio_checkbox = NSButton.alloc().initWithFrame_(
                NSMakeRect(INSET + 8, opt_y + 16, 540, 22))
            self.audio_checkbox.setButtonType_(3)
            self.audio_checkbox.setTitle_(
                "Also send the audio to the formatter (better recovery from bad transcription)")
            v.addSubview_(self.audio_checkbox)
            v.addSubview_(make_hint(
                "Costs a little more; requires an audio-capable formatter model.",
                INSET + 28, opt_y + 2, w=520, h=14, size=10))

            # Prompt editor — keep clearly visible/editable
            prompt_label_y = opt_y - 26
            v.addSubview_(make_section_label(
                "SYSTEM PROMPT TEMPLATE", INSET, prompt_label_y, w=300))
            prompt_bottom = 72
            prompt_h = prompt_label_y - 8 - prompt_bottom
            if prompt_h < 120:
                prompt_h = 120
            pscroll, self.prompt_text = make_text_scroll(
                INSET, prompt_bottom, INNER_W, prompt_h, font_size=11)
            v.addSubview_(pscroll)
            v.addSubview_(make_hint(
                "Placeholders:  {{mode_rules}}   {{dictionary}}   {{corrections}}   "
                "{{context_block}}   {{context_rules}}",
                INSET, 52, w=INNER_W, h=14, size=10))

            sbtn = make_button("Save prompt", INSET, 16, 120, 28,
                               "savePrompt:", self, primary=True)
            v.addSubview_(sbtn)
            rbtn = make_button("Reset to default", INSET + 132, 16, 150, 28,
                               "resetPrompt:", self)
            v.addSubview_(rbtn)
            self.prompt_status = make_hint("", INSET + 300, 20, w=260, h=16)
            v.addSubview_(self.prompt_status)

            item = NSTabViewItem.alloc().initWithIdentifier_("prompt")
            item.setLabel_("Prompt")
            item.setView_(v)
            tabs.addTabViewItem_(item)

        def _load_prompt(self):
            from dictate_core.formatter import DEFAULT_TEMPLATE, _prompt_file_path
            ctx = self.app_controller.cfg.get("context", {})
            for key, cb in self._ctx_boxes.items():
                cb.setState_(1 if ctx.get(key, True) else 0)
            fmt = self.app_controller.cfg.get("formatting", {})
            self.answer_checkbox.setState_(
                1 if fmt.get("answer_questions", False) else 0)
            self.audio_checkbox.setState_(
                1 if fmt.get("send_audio", False) else 0)
            path = _prompt_file_path(fmt.get("prompt_file", "prompt.md"))
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                text = DEFAULT_TEMPLATE
            self.prompt_text.setString_(text)

        def savePrompt_(self, sender):
            from dictate_core.formatter import _prompt_file_path
            flags = {key: bool(cb.state()) for key, cb in self._ctx_boxes.items()}
            try:
                update_config({"context": flags})
                update_config({"formatting": {
                    "answer_questions": bool(self.answer_checkbox.state()),
                    "send_audio": bool(self.audio_checkbox.state())}})
                fmt = self.app_controller.cfg.get("formatting", {})
                path = _prompt_file_path(fmt.get("prompt_file", "prompt.md"))
                path.write_text(str(self.prompt_text.string()), encoding="utf-8")
            except Exception as e:
                self.prompt_status.setStringValue_(f"save failed: {e}")
                return
            self.app_controller.apply_settings()
            self.prompt_status.setStringValue_("Saved.")

        def resetPrompt_(self, sender):
            from dictate_core.formatter import DEFAULT_TEMPLATE, _prompt_file_path
            self.prompt_text.setString_(DEFAULT_TEMPLATE)
            fmt = self.app_controller.cfg.get("formatting", {})
            path = _prompt_file_path(fmt.get("prompt_file", "prompt.md"))
            path.write_text(DEFAULT_TEMPLATE, encoding="utf-8")
            self.app_controller.apply_settings()
            self.prompt_status.setStringValue_("Reset to default.")

        def _build_learning_tab(self, tabs):
            """Dedicated Learning tab: optional OpenRouter review stage."""
            from dictate_core.learning_reviewer import DEFAULT_REVIEWER_MODEL

            v = NSView.alloc().initWithFrame_(
                NSMakeRect(0, 0, CONTENT_W, CONTENT_H))

            make_accent_bar(v, INSET, CONTENT_H - 34, h=18)
            v.addSubview_(make_title(
                "Learning reviewer", INSET + 10, CONTENT_H - 36, w=320))
            v.addSubview_(make_subtitle(
                "Optional OpenRouter pass after you edit an insert. Nothing promotes without approval.",
                INSET + 10, CONTENT_H - 54, w=560, h=16))

            # Enable + model card
            card_h = 166
            card_y = CONTENT_H - 70 - card_h
            make_card(v, INSET - 4, card_y, INNER_W + 8, card_h)

            self.reviewer_checkbox = NSButton.alloc().initWithFrame_(
                NSMakeRect(INSET + 8, card_y + card_h - 36, 540, 22))
            self.reviewer_checkbox.setButtonType_(3)
            self.reviewer_checkbox.setTitle_(
                "Learning reviewer (OpenRouter proposes corrections after you edit)")
            v.addSubview_(self.reviewer_checkbox)
            v.addSubview_(make_hint(
                "Off by default. Approve pairs in History or the live cue.",
                INSET + 28, card_y + card_h - 54, w=520, h=14, size=10))

            v.addSubview_(make_label(
                "Reviewer model", INSET + 8, card_y + 80, w=120, h=18))
            self.reviewer_model_combo = NSComboBox.alloc().initWithFrame_(
                NSMakeRect(INSET + 140, card_y + 77, INNER_W - 156, 26))
            self.reviewer_model_combo.setStringValue_(DEFAULT_REVIEWER_MODEL)
            v.addSubview_(self.reviewer_model_combo)

            self.reviewer_audio_checkbox = NSButton.alloc().initWithFrame_(
                NSMakeRect(INSET + 8, card_y + 46, 540, 22))
            self.reviewer_audio_checkbox.setButtonType_(3)
            self.reviewer_audio_checkbox.setTitle_(
                "Send the original audio with the review (when a recording was kept)")
            v.addSubview_(self.reviewer_audio_checkbox)
            v.addSubview_(make_hint(
                "Privacy: when on, the retained WAV may leave this Mac. Needs keep_recordings.",
                INSET + 28, card_y + 29, w=520, h=14, size=10))

            v.addSubview_(make_label(
                "Min confidence", INSET + 8, card_y + 6, w=120, h=18))
            self.reviewer_conf_field = NSTextField.alloc().initWithFrame_(
                NSMakeRect(INSET + 140, card_y + 4, 80, 24))
            self.reviewer_conf_field.setStringValue_("0.55")
            self.reviewer_conf_field.setToolTip_("0–1; discard lower-confidence pairs")
            v.addSubview_(self.reviewer_conf_field)

            # Prompt editor
            v.addSubview_(make_section_label(
                "REVIEWER SYSTEM PROMPT", INSET, card_y - 26, w=300))
            prompt_bottom = 72
            prompt_h = card_y - 34 - prompt_bottom
            if prompt_h < 120:
                prompt_h = 120
            lscroll, self.learning_prompt_text = make_text_scroll(
                INSET, prompt_bottom, INNER_W, prompt_h, font_size=11)
            v.addSubview_(lscroll)
            v.addSubview_(make_hint(
                "Saved to ~/.golos/learning_prompt.md (or [learning] reviewer_prompt_file).",
                INSET, 52, w=INNER_W, h=14, size=10))

            sbtn = make_button("Save learning", INSET, 16, 140, 28,
                               "saveLearning:", self, primary=True)
            v.addSubview_(sbtn)
            rbtn = make_button("Reset prompt", INSET + 152, 16, 140, 28,
                               "resetLearningPrompt:", self)
            v.addSubview_(rbtn)
            self.learning_status = make_hint("", INSET + 310, 20, w=250, h=16)
            v.addSubview_(self.learning_status)

            item = NSTabViewItem.alloc().initWithIdentifier_("learning")
            item.setLabel_("Learning")
            item.setView_(v)
            tabs.addTabViewItem_(item)

        def _load_learning(self):
            from dictate_core.learning_reviewer import (
                DEFAULT_MIN_CONFIDENCE,
                DEFAULT_REVIEWER_MODEL,
                DEFAULT_REVIEWER_PROMPT,
                prompt_file_path,
            )
            learning = self.app_controller.cfg.get("learning") or {}
            self.reviewer_checkbox.setState_(
                1 if learning.get("reviewer_enabled", False) else 0)
            self.reviewer_model_combo.setStringValue_(
                learning.get("reviewer_model") or DEFAULT_REVIEWER_MODEL)
            self.reviewer_audio_checkbox.setState_(
                1 if learning.get("reviewer_send_audio", True) else 0)
            conf = learning.get("reviewer_min_confidence", DEFAULT_MIN_CONFIDENCE)
            self.reviewer_conf_field.setStringValue_(str(conf))
            path = prompt_file_path(
                learning.get("reviewer_prompt_file", "learning_prompt.md"))
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                text = DEFAULT_REVIEWER_PROMPT
            self.learning_prompt_text.setString_(text)

        def saveLearning_(self, sender):
            from dictate_core.learning_reviewer import (
                DEFAULT_MIN_CONFIDENCE,
                prompt_file_path,
            )
            try:
                conf_raw = str(self.reviewer_conf_field.stringValue()).strip()
                conf = float(conf_raw) if conf_raw else DEFAULT_MIN_CONFIDENCE
                conf = max(0.0, min(1.0, conf))
                update_config({"learning": {
                    "reviewer_enabled": bool(self.reviewer_checkbox.state()),
                    "reviewer_model": str(self.reviewer_model_combo.stringValue()),
                    "reviewer_send_audio": bool(self.reviewer_audio_checkbox.state()),
                    "reviewer_min_confidence": conf,
                }})
                learning = self.app_controller.cfg.get("learning") or {}
                path = prompt_file_path(
                    learning.get("reviewer_prompt_file", "learning_prompt.md"))
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(str(self.learning_prompt_text.string()),
                                encoding="utf-8")
            except Exception as e:
                self.learning_status.setStringValue_(f"save failed: {e}")
                return
            self.app_controller.apply_settings()
            self.learning_status.setStringValue_("Saved.")

        def resetLearningPrompt_(self, sender):
            from dictate_core.learning_reviewer import (
                DEFAULT_REVIEWER_PROMPT,
                prompt_file_path,
            )
            self.learning_prompt_text.setString_(DEFAULT_REVIEWER_PROMPT)
            learning = self.app_controller.cfg.get("learning") or {}
            path = prompt_file_path(
                learning.get("reviewer_prompt_file", "learning_prompt.md"))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(DEFAULT_REVIEWER_PROMPT, encoding="utf-8")
            self.app_controller.apply_settings()
            self.learning_status.setStringValue_("Prompt reset to default.")

        def _build_general_tab(self, tabs):
            v = NSView.alloc().initWithFrame_(
                NSMakeRect(0, 0, CONTENT_W, CONTENT_H))

            make_accent_bar(v, INSET, CONTENT_H - 30, h=16)
            v.addSubview_(make_title(
                "General", INSET + 10, CONTENT_H - 32, w=200, h=20))
            v.addSubview_(make_subtitle(
                "Speech recognition, formatting, and the menu-bar bubble.",
                INSET + 10, CONTENT_H - 48, w=500, h=14))

            # --- Speech recognition (compact card) ---
            y = CONTENT_H - 70
            v.addSubview_(make_section_label("SPEECH RECOGNITION", INSET, y, w=220))
            card_top = y - 4
            card_h = 78
            make_card(v, INSET - 4, card_top - card_h, INNER_W + 8, card_h)
            y = card_top - 28

            v.addSubview_(make_label("STT backend", INSET + 8, y, w=100, h=16))
            self.backend_popup = NSPopUpButton.alloc().initWithFrame_pullsDown_(
                NSMakeRect(INSET + 120, y - 4, 140, 26), False)
            self.backend_popup.addItemsWithTitles_(["openrouter", "mlx"])
            self.backend_popup.setTarget_(self)
            self.backend_popup.setAction_("backendChanged:")
            v.addSubview_(self.backend_popup)
            self.local_model_button = NSButton.alloc().initWithFrame_(
                NSMakeRect(INSET + 270, y - 4, 200, 26))
            self.local_model_button.setBezelStyle_(1)
            self.local_model_button.setTarget_(self)
            self.local_model_button.setAction_("downloadLocalModel:")
            v.addSubview_(self.local_model_button)
            y -= 32

            v.addSubview_(make_label("STT model", INSET + 8, y, w=100, h=16))
            self.stt_model_combo = NSComboBox.alloc().initWithFrame_(
                NSMakeRect(INSET + 120, y - 4, 240, 26))
            v.addSubview_(self.stt_model_combo)
            v.addSubview_(make_label("Languages", INSET + 372, y, w=80, h=16))
            self.lang_field = NSTextField.alloc().initWithFrame_(
                NSMakeRect(INSET + 450, y - 4, INNER_W - 458, 24))
            self.lang_field.setPlaceholderString_("en, uk")
            self.lang_field.setToolTip_("comma-separated, empty = auto-detect")
            v.addSubview_(self.lang_field)

            # --- Formatting ---
            y = card_top - card_h - 20
            v.addSubview_(make_section_label("FORMATTING", INSET, y, w=200))
            card_top = y - 4
            card_h = 112
            make_card(v, INSET - 4, card_top - card_h, INNER_W + 8, card_h)
            y = card_top - 28

            v.addSubview_(make_label("Formatter model", INSET + 8, y, w=120, h=16))
            self.fmt_model_combo = NSComboBox.alloc().initWithFrame_(
                NSMakeRect(INSET + 140, y - 4, INNER_W - 156, 26))
            v.addSubview_(self.fmt_model_combo)
            y -= 30

            self.llm_checkbox = NSButton.alloc().initWithFrame_(
                NSMakeRect(INSET + 8, y, 500, 20))
            self.llm_checkbox.setButtonType_(3)
            self.llm_checkbox.setTitle_(
                "Format with LLM (uncheck for fastest raw insert)")
            v.addSubview_(self.llm_checkbox)
            y -= 24

            self.fast_checkbox = NSButton.alloc().initWithFrame_(
                NSMakeRect(INSET + 8, y, 500, 20))
            self.fast_checkbox.setButtonType_(3)
            self.fast_checkbox.setTitle_(
                "Fast mode (skip LLM cleanup for short dictations)")
            v.addSubview_(self.fast_checkbox)
            y -= 16
            v.addSubview_(make_hint(
                "Short inserts become instant; corrections still apply.",
                INSET + 28, y, w=480, h=12, size=10))

            # --- API key ---
            y = card_top - card_h - 20
            v.addSubview_(make_section_label("OPENROUTER", INSET, y, w=200))
            card_top = y - 4
            card_h = 42
            make_card(v, INSET - 4, card_top - card_h, INNER_W + 8, card_h)
            y = card_top - 28
            v.addSubview_(make_label("API key", INSET + 8, y, w=70, h=16))
            self.key_field = NSSecureTextField.alloc().initWithFrame_(
                NSMakeRect(INSET + 90, y - 4, INNER_W - 106, 24))
            v.addSubview_(self.key_field)

            # --- Insertion (clipboard policy) ---
            y = card_top - card_h - 20
            v.addSubview_(make_section_label("INSERTION", INSET, y, w=200))
            card_top = y - 4
            card_h = 72
            make_card(v, INSET - 4, card_top - card_h, INNER_W + 8, card_h)
            y = card_top - 28

            self.restore_clipboard_checkbox = NSButton.alloc().initWithFrame_(
                NSMakeRect(INSET + 8, y, 520, 20))
            self.restore_clipboard_checkbox.setButtonType_(3)
            self.restore_clipboard_checkbox.setTitle_(
                "Restore clipboard after multi-line paste (recommended)")
            self.restore_clipboard_checkbox.setToolTip_(
                "Multi-line dictation temporarily uses the pasteboard + Cmd+V. "
                "When checked (default), golos restores the previous clipboard "
                "asynchronously after a short delay, and only if you have not "
                "copied something else in the meantime. Uncheck only if a slow "
                "app pastes the wrong content — the transcript then stays on "
                "the clipboard. Single-line text is typed without the pasteboard. "
                "History → Copy always leaves text on the clipboard intentionally.")
            v.addSubview_(self.restore_clipboard_checkbox)
            y -= 20
            v.addSubview_(make_hint(
                "Default: clear temporary paste without blocking the UI. "
                "Uncheck to leave transcript on the clipboard (compat).",
                INSET + 28, y, w=500, h=24, size=10))

            # --- Bubble & hotkey ---
            y = card_top - card_h - 20
            v.addSubview_(make_section_label(
                "BUBBLE & HOTKEY", INSET, y, w=220))
            card_top = y - 4
            card_h = 92
            make_card(v, INSET - 4, card_top - card_h, INNER_W + 8, card_h)
            y = card_top - 28

            v.addSubview_(make_label("Bubble style", INSET + 8, y, w=100, h=16))
            self.bubble_popup = NSPopUpButton.alloc().initWithFrame_pullsDown_(
                NSMakeRect(INSET + 120, y - 4, 90, 26), False)
            self.bubble_popup.addItemsWithTitles_(["notch", "corner"])
            v.addSubview_(self.bubble_popup)
            v.addSubview_(make_hint("(restart)", INSET + 216, y, w=55, h=14, size=10))
            v.addSubview_(make_label("Hold key", INSET + 280, y, w=70, h=16))
            self.holdkey_popup = NSPopUpButton.alloc().initWithFrame_pullsDown_(
                NSMakeRect(INSET + 355, y - 4, 140, 26), False)
            self.holdkey_popup.addItemsWithTitles_(
                ["fn", "right_option", "right_command", "f5"])
            v.addSubview_(self.holdkey_popup)
            y -= 30

            v.addSubview_(make_label("Input sensitivity", INSET + 8, y, w=120, h=16))
            self.sens_slider = NSSlider.alloc().initWithFrame_(
                NSMakeRect(INSET + 140, y - 4, 220, 24))
            self.sens_slider.setMinValue_(0.5)
            self.sens_slider.setMaxValue_(2.5)
            self.sens_slider.setDoubleValue_(1.0)
            self.sens_slider.setTarget_(self)
            self.sens_slider.setAction_("sensitivityChanged:")
            v.addSubview_(self.sens_slider)
            self.sens_label = make_label("1.0", INSET + 370, y, w=50, h=16)
            v.addSubview_(self.sens_label)
            y -= 26

            self.bubble_text_checkbox = NSButton.alloc().initWithFrame_(
                NSMakeRect(INSET + 8, y, 480, 20))
            self.bubble_text_checkbox.setButtonType_(3)
            self.bubble_text_checkbox.setTitle_(
                "Show status words in the top animation")
            v.addSubview_(self.bubble_text_checkbox)

            # Footer actions — keep clear of cards (card bottom ~48)
            save_btn = make_button("Save", INSET, 14, 100, 28,
                                   "saveGeneral:", self, primary=True)
            v.addSubview_(save_btn)
            fetch_btn = make_button("Fetch models", INSET + 112, 14, 130, 28,
                                    "refreshModels:", self)
            v.addSubview_(fetch_btn)
            self.status_label = make_hint("", INSET + 260, 18, w=300, h=18)
            self.status_label.setFont_(NSFont.systemFontOfSize_(11))
            v.addSubview_(self.status_label)

            item = NSTabViewItem.alloc().initWithIdentifier_("general")
            item.setLabel_("General")
            item.setView_(v)
            tabs.addTabViewItem_(item)

        def _make_table(self, columns):
            """Small editable cell-based table; columns = [(ident, title, width)]."""
            scroll = NSScrollView.alloc().init()
            scroll.setHasVerticalScroller_(True)
            scroll.setBorderType_(0)
            scroll.setDrawsBackground_(False)
            table = NSTableView.alloc().initWithFrame_(NSMakeRect(0, 0, 100, 100))
            for ident, title, width in columns:
                col = NSTableColumn.alloc().initWithIdentifier_(ident)
                col.headerCell().setStringValue_(title)
                col.setWidth_(width)
                col.setEditable_(True)
                table.addTableColumn_(col)
            table.setDataSource_(self)
            table.setDelegate_(self)
            style_table(table)
            scroll.setDocumentView_(table)
            return scroll, table

        def _build_dictionary_tab(self, tabs):
            v = NSView.alloc().initWithFrame_(
                NSMakeRect(0, 0, CONTENT_W, CONTENT_H))
            paths = self.app_controller.cfg["paths"]

            make_accent_bar(v, INSET, CONTENT_H - 34, h=18)
            v.addSubview_(make_title(
                "Dictionary", INSET + 10, CONTENT_H - 36, w=240))
            v.addSubview_(make_subtitle(
                "Terms bias recognition and formatting; corrections rewrite known mistakes.",
                INSET + 10, CONTENT_H - 54, w=560))

            # Terms section
            y = CONTENT_H - 80
            v.addSubview_(make_section_label(
                "TERMS  ·  dictionary.txt", INSET, y, w=360))
            terms_h = 190
            terms_y = y - 8 - terms_h
            make_card(v, INSET - 4, terms_y - 36, INNER_W + 8, terms_h + 44)
            tscroll, self.terms_table = self._make_table(
                [("term", "Term", INNER_W - 16)])
            tscroll.setFrame_(NSMakeRect(INSET, terms_y, INNER_W, terms_h))
            v.addSubview_(tscroll)
            for title, action, x in (("+", "addTerm:", INSET),
                                     ("−", "removeTerm:", INSET + 44)):
                btn = make_button(title, x, terms_y - 30, 40, 26, action, self)
                v.addSubview_(btn)
            tsbtn = make_button(
                "Save terms", CONTENT_W - INSET - 130, terms_y - 30,
                130, 26, "saveTerms:", self)
            v.addSubview_(tsbtn)

            # Corrections section
            y = terms_y - 66
            v.addSubview_(make_section_label(
                "CORRECTIONS  ·  corrections.tsv", INSET, y, w=360))
            corr_h = 150
            corr_y = y - 8 - corr_h
            make_card(v, INSET - 4, corr_y - 36, INNER_W + 8, corr_h + 44)
            half = (INNER_W - 12) / 2
            cscroll, self.corr_table = self._make_table(
                [("wrong", "Wrong", half), ("right", "Right", half)])
            cscroll.setFrame_(NSMakeRect(INSET, corr_y, INNER_W, corr_h))
            v.addSubview_(cscroll)
            for title, action, x in (("+", "addCorrection:", INSET),
                                     ("−", "removeCorrection:", INSET + 44)):
                btn = make_button(title, x, corr_y - 30, 40, 26, action, self)
                v.addSubview_(btn)
            csbtn = make_button(
                "Save corrections", CONTENT_W - INSET - 140, corr_y - 30,
                140, 26, "saveCorrections:", self)
            v.addSubview_(csbtn)
            self._paths = paths

            item = NSTabViewItem.alloc().initWithIdentifier_("dictionary")
            item.setLabel_("Dictionary")
            item.setView_(v)
            tabs.addTabViewItem_(item)

        # -- loading ---------------------------------------------------------

        def _load_general(self):
            cfg = self.app_controller.cfg
            stt = cfg.get("stt", {})
            backend = stt.get("backend", "openrouter")
            from dictate_core.stt import local_model_support
            local_supported, _ = local_model_support()
            mlx_item = self.backend_popup.itemWithTitle_("mlx")
            if mlx_item is not None:
                mlx_item.setEnabled_(local_supported)
            if backend == "mlx" and not local_supported:
                backend = "openrouter"
            self.backend_popup.selectItemWithTitle_(
                backend if backend in ("mlx", "openrouter") else "openrouter")
            self._load_stt_model_value()
            self.fmt_model_combo.setStringValue_(
                cfg.get("formatting", {}).get("model", DEFAULT_CHAT_MODEL))
            langs = cfg.get("stt", {}).get("languages", [])
            self.lang_field.setStringValue_(
                ", ".join(langs) if isinstance(langs, list) else str(langs))
            api_key = (cfg.get("openrouter") or {}).get("api_key", "")
            if isinstance(api_key, list):  # defensive: was once saved as char array
                api_key = "".join(str(c) for c in api_key)
            self.key_field.setStringValue_(api_key)
            self.bubble_popup.selectItemWithTitle_(
                cfg.get("bubble", {}).get("style", "notch"))
            self.holdkey_popup.selectItemWithTitle_(
                cfg.get("hotkey", {}).get("hold_key", "fn"))
            sens = float(cfg.get("bubble", {}).get("sensitivity", 1.0))
            self.sens_slider.setDoubleValue_(sens)
            self.sens_label.setStringValue_(f"{sens:.1f}")
            self.bubble_text_checkbox.setState_(
                1 if cfg.get("bubble", {}).get("show_text", True) else 0)
            self.llm_checkbox.setState_(
                1 if cfg.get("formatting", {}).get("enabled", True) else 0)
            self.fast_checkbox.setState_(
                1 if cfg.get("formatting", {}).get("fast_mode", False) else 0)
            self.restore_clipboard_checkbox.setState_(
                1 if cfg.get("insert", {}).get("restore_clipboard", True) else 0)
            self._update_local_model_button()

        def _load_stt_model_value(self):
            cfg = self.app_controller.cfg
            stt = cfg.get("stt", {})
            if self.backend_popup.titleOfSelectedItem() == "openrouter":
                # The public /models catalog doesn't list transcription models;
                # use the curated verified list (combo stays editable).
                current = stt.get("openrouter", {}).get("model", DEFAULT_STT_MODEL)
                self.stt_model_combo.removeAllItems()
                self.stt_model_combo.addItemsWithObjectValues_(
                    transcription_model_ids())
                self.stt_model_combo.setStringValue_(current)
            else:
                self.stt_model_combo.removeAllItems()
                self.stt_model_combo.setStringValue_(
                    stt.get("mlx_model", "mlx-community/whisper-large-v3-turbo"))

        def _load_dictionary_files(self):
            from .dictionary import load_terms, load_corrections
            self._terms = load_terms(self._paths["dictionary"])
            self._corrections = [list(p) for p in
                                 load_corrections(self._paths["corrections"])]
            self.terms_table.reloadData()
            self.corr_table.reloadData()

        def _load_history(self):
            # Home list: one latest derived row per run_id; legacy lines alone.
            # JSONL stays append-only — grouping is display-only.
            try:
                from .history import load_history_home
                records = load_history_home(
                    self.app_controller.cfg["paths"]["history"],
                    limit=500)
            except Exception:
                records = []
                try:
                    from .history import group_history_for_home, normalize_record
                    lines = Path(self.app_controller.cfg["paths"]["history"]) \
                        .read_text(encoding="utf-8").splitlines()
                    raw_rows = []
                    for line in reversed(lines[-2000:]):
                        try:
                            norm = normalize_record(json.loads(line))
                        except json.JSONDecodeError:
                            continue
                        if norm is not None:
                            raw_rows.append(norm)
                    records = group_history_for_home(raw_rows, limit=500)
                except FileNotFoundError:
                    pass
            self._records = records
            self.table.reloadData()
            n = len(records)
            if n == 0:
                self.history_count_label.setStringValue_(
                    "No dictations yet — hold your key and speak. Logs stay on this Mac.")
            elif n == 1:
                self.history_count_label.setStringValue_(
                    "1 entry · local history.jsonl (newest first)")
            else:
                self.history_count_label.setStringValue_(
                    f"{n} entries · local history.jsonl (newest first)")

        # -- actions (ObjC selectors) ---------------------------------------

        def backendChanged_(self, sender):
            self._load_stt_model_value()
            self._update_local_model_button()

        def _local_model_name(self):
            if self.backend_popup.titleOfSelectedItem() == "mlx":
                return str(self.stt_model_combo.stringValue())
            return str(self.app_controller.cfg.get("stt", {}).get(
                "mlx_model", "mlx-community/whisper-large-v3-turbo"))

        def _update_local_model_button(self):
            from dictate_core.stt import (
                local_model_is_downloaded,
                local_model_support,
            )
            supported, reason = local_model_support()
            if not supported:
                self.local_model_button.setTitle_("Local model unavailable")
                self.local_model_button.setEnabled_(False)
                self.local_model_button.setToolTip_(reason)
                return
            if local_model_is_downloaded(self._local_model_name()):
                self.local_model_button.setTitle_("Local model ✓ ready")
                self.local_model_button.setEnabled_(False)
                self.local_model_button.setToolTip_(
                    "Optional MLX model weights are already downloaded.")
            else:
                self.local_model_button.setTitle_("Download local (~1.5 GB)")
                self.local_model_button.setEnabled_(True)
                self.local_model_button.setToolTip_(
                    "Optional. OpenRouter works without this download.")

        def downloadLocalModel_(self, sender):
            from dictate_core.stt import download_local_model
            model = self._local_model_name()
            self.local_model_button.setEnabled_(False)
            self.local_model_button.setTitle_("Downloading…")
            self.status_label.setStringValue_(
                "Downloading optional local model; OpenRouter remains available.")

            def work():
                try:
                    download_local_model(model)
                except Exception as e:
                    AppHelper.callAfter(self._local_model_download_failed, str(e))
                else:
                    AppHelper.callAfter(self._local_model_downloaded)

            threading.Thread(target=work, daemon=True).start()

        def _local_model_downloaded(self):
            self._update_local_model_button()
            self.status_label.setStringValue_("Local model downloaded and ready.")

        def _local_model_download_failed(self, message):
            self._update_local_model_button()
            self.status_label.setStringValue_(f"local download failed: {message}")

        def sensitivityChanged_(self, sender):
            self.sens_label.setStringValue_(f"{self.sens_slider.doubleValue():.1f}")

        def saveGeneral_(self, sender):
            from dictate_core.stt import (
                local_model_is_downloaded,
                local_model_support,
                validate_languages,
            )
            backend = self.backend_popup.titleOfSelectedItem()
            if backend == "mlx":
                supported, reason = local_model_support()
                if not supported:
                    self.status_label.setStringValue_(reason)
                    return
                if not local_model_is_downloaded(
                        str(self.stt_model_combo.stringValue())):
                    self.status_label.setStringValue_(
                        "Download the local model before selecting MLX.")
                    return
            langs = validate_languages(
                str(self.lang_field.stringValue()).split(","))
            updates = {
                "openrouter": {"api_key": self.key_field.stringValue()},
                "stt": {"backend": backend, "languages": langs},
                "formatting": {
                    "provider": "openrouter",
                    "model": self.fmt_model_combo.stringValue(),
                    "enabled": bool(self.llm_checkbox.state()),
                    "fast_mode": bool(self.fast_checkbox.state()),
                },
                "bubble": {"style": self.bubble_popup.titleOfSelectedItem(),
                           "sensitivity": round(self.sens_slider.doubleValue(), 1),
                           "show_text": bool(self.bubble_text_checkbox.state())},
                "hotkey": {"hold_key": self.holdkey_popup.titleOfSelectedItem()},
                "insert": {
                    "restore_clipboard": bool(
                        self.restore_clipboard_checkbox.state()),
                },
            }
            if backend == "openrouter":
                updates["stt.openrouter"] = {"model": self.stt_model_combo.stringValue()}
            else:
                updates["stt"]["mlx_model"] = self.stt_model_combo.stringValue()
            try:
                update_config(updates)
            except Exception as e:
                self.status_label.setStringValue_(f"save failed: {e}")
                return
            self.app_controller.apply_settings()
            self.status_label.setStringValue_("Saved.")

        def refreshModels_(self, sender):
            self.status_label.setStringValue_("Fetching models…")
            key = self.key_field.stringValue() or \
                get_api_key(self.app_controller.cfg)

            def work():
                try:
                    models = fetch_models(key)
                except Exception as e:
                    AppHelper.callAfter(self._models_failed, str(e))
                else:
                    AppHelper.callAfter(self._models_loaded, models)

            threading.Thread(target=work, daemon=True).start()

        # -- dictionary tables ------------------------------------------------

        def _read_comments(self, path) -> list[str]:
            try:
                return [l for l in Path(path).read_text(encoding="utf-8")
                        .splitlines() if l.lstrip().startswith("#")]
            except FileNotFoundError:
                return []

        def saveTerms_(self, sender):
            lines = self._read_comments(self._paths["dictionary"])
            lines += [t.strip() for t in self._terms if t.strip()]
            Path(self._paths["dictionary"]).write_text(
                "\n".join(lines) + "\n", encoding="utf-8")
            self.app_controller.reload_dictionary()

        def saveCorrections_(self, sender):
            lines = self._read_comments(self._paths["corrections"])
            lines += [f"{w.strip()}\t{r.strip()}" for w, r in self._corrections
                      if w.strip() and r.strip()]
            Path(self._paths["corrections"]).write_text(
                "\n".join(lines) + "\n", encoding="utf-8")
            self.app_controller.reload_dictionary()

        def addTerm_(self, sender):
            self._terms.append("")
            self.terms_table.reloadData()
            row = len(self._terms) - 1
            self.terms_table.selectRowIndexes_byExtendingSelection_(
                NSIndexSet.indexSetWithIndex_(row), False)
            self.terms_table.editColumn_row_withEvent_select_(0, row, None, True)

        def removeTerm_(self, sender):
            row = self.terms_table.selectedRow()
            if 0 <= row < len(self._terms):
                del self._terms[row]
                self.terms_table.reloadData()

        def addCorrection_(self, sender):
            self._corrections.append(["", ""])
            self.corr_table.reloadData()
            row = len(self._corrections) - 1
            self.corr_table.selectRowIndexes_byExtendingSelection_(
                NSIndexSet.indexSetWithIndex_(row), False)
            self.corr_table.editColumn_row_withEvent_select_(0, row, None, True)

        def removeCorrection_(self, sender):
            row = self.corr_table.selectedRow()
            if 0 <= row < len(self._corrections):
                del self._corrections[row]
                self.corr_table.reloadData()

        def refreshHistory_(self, sender):
            self._load_history()
            self._load_suggestions()

        def _selected_history_record(self):
            row = self.table.selectedRow()
            if 0 <= row < len(self._records):
                return self._records[row]
            return None

        def copyHistoryText_(self, sender):
            """Copy final text (or raw fallback) without changing focus."""
            rec = self._selected_history_record()
            payload = self.app_controller.copy_ready_for_record(rec) if rec else {}
            text = payload.get("text")
            if not text:
                self.history_action_status.setStringValue_("No text to copy")
                return
            try:
                from AppKit import NSPasteboard, NSPasteboardTypeString
                pb = NSPasteboard.generalPasteboard()
                pb.clearContents()
                pb.setString_forType_(str(text), NSPasteboardTypeString)
                source = payload.get("source") or "text"
                self.history_action_status.setStringValue_(f"Copied {source}")
            except Exception as e:
                log.warning("History copy failed: %s", e)
                self.history_action_status.setStringValue_("Copy failed")

        def retryHistory_(self, sender):
            """Retry on a worker; never auto-insert into the Settings window."""
            rec = self._selected_history_record()
            if not rec:
                self.history_action_status.setStringValue_("Select a run first")
                return
            caps = self.app_controller.retry_capabilities_for_record(rec)
            if not any(caps.get(k) for k in (
                    "can_retry_stt", "can_retry_format", "can_retry_insert")):
                self.history_action_status.setStringValue_(
                    caps.get("reason") or "Nothing retryable")
                return
            self.retry_history_button.setEnabled_(False)
            self.history_action_status.setStringValue_("Retrying…")

            def work():
                result = self.app_controller.retry_failed_stage(
                    rec, insert=False)
                AppHelper.callAfter(self._retry_history_finished, result)

            threading.Thread(target=work, daemon=True).start()

        def _retry_history_finished(self, result):
            self.retry_history_button.setEnabled_(True)
            self._load_history()
            if self._records:
                self.table.selectRowIndexes_byExtendingSelection_(
                    NSIndexSet.indexSetWithIndex_(0), False)
                self.detail_text.setString_(self._render_detail(self._records[0]))
            if result.get("busy"):
                self.history_action_status.setStringValue_(
                    "Busy — live dictation running")
            elif result.get("ok"):
                self.history_action_status.setStringValue_(
                    "Retry saved — ready to copy")
            else:
                msg = str(result.get("error") or "Retry failed")
                self.history_action_status.setStringValue_(_trunc(msg, 24))

        def showHistoryAudio_(self, sender):
            rec = self._selected_history_record()
            path = str((rec or {}).get("audio") or "")
            if not path or not Path(path).is_file():
                self.history_action_status.setStringValue_("No retained audio")
                return
            try:
                from AppKit import NSWorkspace
                NSWorkspace.sharedWorkspace() \
                    .selectFile_inFileViewerRootedAtPath_(path, "")
                self.history_action_status.setStringValue_("Shown in Finder")
            except Exception as e:
                log.warning("Could not reveal history audio: %s", e)
                self.history_action_status.setStringValue_("Could not show audio")

        # -- suggestions ------------------------------------------------------

        def _load_suggestions(self):
            from .learning import aggregate_suggestions
            paths = self.app_controller.cfg["paths"]
            self._suggestions = aggregate_suggestions(
                paths["suggestions"], paths["dismissed"])
            self.sug_table.reloadData()

        def _selected_suggestion(self):
            row = self.sug_table.selectedRow()
            if 0 <= row < len(self._suggestions):
                return self._suggestions[row]
            return None

        def checkForEdits_(self, sender):
            from .learning import capture_edit_async
            capture_edit_async(self.app_controller,
                               lambda pairs: self._load_suggestions())

        def addToCorrections_(self, sender):
            from .learning import promote_to_corrections, dismiss_pair
            s = self._selected_suggestion()
            if not s:
                return
            paths = self.app_controller.cfg["paths"]
            promote_to_corrections(paths["corrections"], s["wrong"], s["right"])
            dismiss_pair(paths["dismissed"], s["wrong"], s["right"])
            self.app_controller.reload_dictionary()
            self.app_controller.bubble.notice(
                f'learned "{_trunc(s["wrong"])} → {_trunc(s["right"])}"', "success")
            self._load_suggestions()

        def addToDictionary_(self, sender):
            from .learning import promote_to_dictionary, dismiss_pair
            s = self._selected_suggestion()
            if not s:
                return
            paths = self.app_controller.cfg["paths"]
            promote_to_dictionary(paths["dictionary"], s["right"])
            dismiss_pair(paths["dismissed"], s["wrong"], s["right"])
            self.app_controller.reload_dictionary()
            self.app_controller.bubble.notice(
                f'✓ "{_trunc(s["right"])}" in dictionary', "success")
            self._load_suggestions()

        def dismissSuggestion_(self, sender):
            from .learning import dismiss_pair
            s = self._selected_suggestion()
            if not s:
                return
            dismiss_pair(self.app_controller.cfg["paths"]["dismissed"],
                         s["wrong"], s["right"])
            self._load_suggestions()

        # -- model fetch callbacks (main thread) ----------------------------

        def _models_loaded(self, models):
            audio_ids = audio_model_ids(models)
            text_ids = text_model_ids(models)
            # The /models catalog has no transcription models: in openrouter
            # mode the STT combo keeps the curated list; the fetch only feeds
            # the formatter combo (and the mlx-irrelevant audio list).
            if self.backend_popup.titleOfSelectedItem() == "openrouter":
                combos = ((self.fmt_model_combo, text_ids),)
            else:
                combos = ((self.stt_model_combo, audio_ids),
                          (self.fmt_model_combo, text_ids))
            for combo, ids in combos:
                current = combo.stringValue()
                combo.removeAllItems()
                combo.addItemsWithObjectValues_(ids)
                combo.setStringValue_(current)  # keep current value even if unlisted
            self.status_label.setStringValue_(
                f"{len(models)} models loaded ({len(audio_ids)} audio-capable)")

        def _models_failed(self, error):
            # combos keep showing the current config values
            self.status_label.setStringValue_(f"fetch failed: {error}")

        # -- table data sources / delegates -----------------------------------

        def numberOfRowsInTableView_(self, table):
            if table == getattr(self, "sug_table", None):
                return len(self._suggestions)
            if table == getattr(self, "terms_table", None):
                return len(self._terms)
            if table == getattr(self, "corr_table", None):
                return len(self._corrections)
            return len(self._records)

        def tableView_objectValueForTableColumn_row_(self, table, column, row):
            ident = column.identifier()
            if table == getattr(self, "sug_table", None):
                s = self._suggestions[row]
                if ident == "wrong":
                    return s["wrong"]
                if ident == "right":
                    return s["right"]
                if ident == "count":
                    return s["count"]
                return s["last_app"]
            if table == getattr(self, "terms_table", None):
                return self._terms[row]
            if table == getattr(self, "corr_table", None):
                return self._corrections[row][0 if ident == "wrong" else 1]
            rec = self._records[row]
            if ident == "time":
                return str(rec.get("ts", ""))[:19].replace("T", " ")
            if ident == "app":
                return rec.get("app", "")
            raw = (rec.get("raw") or "").replace("\n", " ").strip()
            final = (rec.get("final") or "").replace("\n", " ").strip()
            if raw == final:
                text = final or raw or "—"
            else:
                text = f"{raw} → {final}"
            status = rec.get("status") or ""
            if status and status != "success":
                text = f"[{status}] {text}"
            return text if len(text) <= 100 else text[:97] + "…"

        def tableView_setObjectValue_forTableColumn_row_(self, table, value,
                                                         column, row):
            ident = column.identifier()
            if table == getattr(self, "terms_table", None):
                self._terms[row] = str(value).strip()
            elif table == getattr(self, "corr_table", None):
                self._corrections[row][0 if ident == "wrong" else 1] = \
                    str(value).strip()

        def tableViewSelectionDidChange_(self, notification):
            if notification.object() != getattr(self, "table", None):
                return
            row = self.table.selectedRow()
            if 0 <= row < len(self._records):
                rec = self._records[row]
                self.detail_text.setString_(self._render_detail(rec))
            else:
                self.detail_text.setString_(
                    "Select a row above to inspect raw text, final insert, and context.")

        def _render_detail(self, rec):
            from .formatter import render_context_block
            parts = []
            ts = str(rec.get("ts", ""))[:19].replace("T", " ")
            app = rec.get("app", "") or ""
            status = rec.get("status") or ""
            stage = rec.get("stage") or ""
            header_bits = [p for p in (ts, app) if p]
            if status:
                header_bits.append(status)
            if stage and stage != "complete":
                header_bits.append(f"stage {stage}")
            try:
                attempts_count = int(rec.get("attempts_count") or 1)
            except (TypeError, ValueError):
                attempts_count = 1
            if attempts_count > 1:
                header_bits.append(f"{attempts_count} attempts")
            if header_bits:
                parts.append("  ·  ".join(header_bits))
            parts.append("")
            parts.append("RAW")
            parts.append(rec.get("raw", "") or "—")
            parts.append("")
            parts.append("FINAL")
            parts.append(rec.get("final", "") or "—")
            err = rec.get("error")
            if err:
                parts.append("")
                parts.append("ERROR")
                parts.append(str(err))
            ctx = rec.get("context") or {}
            if ctx:
                parts.append("")
                parts.append("CONTEXT")
                parts.append(render_context_block(ctx))
            meta = []
            if rec.get("fast"):
                meta.append("fast mode")
            if rec.get("format_fallback"):
                meta.append("format fallback")
            # Only claim retained audio when the flag is honest (file on disk).
            # Path may still appear in diagnostics; do not treat path alone.
            if rec.get("audio_retained"):
                meta.append("audio retained")
            if attempts_count > 1:
                meta.append(f"{attempts_count} attempts")
            if meta:
                parts.append("")
                parts.append(" · ".join(meta))
            return "\n".join(parts)

        # -- window delegate -------------------------------------------------

        def windowWillClose_(self, notification):
            # Accessory app: with no key window left, macOS returns focus to the
            # previously active app on its own.
            pass

        # -- public -----------------------------------------------------------

        def show(self):
            # Refresh home dashboard each open so History stays current.
            try:
                self._load_history()
                self._load_suggestions()
            except Exception:
                log.exception("settings show: history refresh failed")
            if getattr(self, "tabs", None) is not None:
                try:
                    self.tabs.selectFirstTabViewItem_(None)
                except Exception:
                    pass
            NSApp.activateIgnoringOtherApps_(True)
            self.window.makeKeyAndOrderFront_(None)

    return SettingsController.alloc().initWithAppController_(app_controller)
