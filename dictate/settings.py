"""Menu-bar status item and the Settings window (General / Dictionary / History).

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

WINDOW_W, WINDOW_H = 620.0, 460.0

# ObjC class names are process-global: define each exactly once.
_class_cache: dict = {}


def _trunc(s: str, n: int = 24) -> str:
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

            def testInsertion_(self, sender):
                from .insert import insert_text
                insert_text("✅ golos insertion test")

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
        NSTextView, NSTableView, NSTableColumn, NSFont, NSColor,
        NSWindowStyleMaskTitled, NSWindowStyleMaskClosable,
        NSBackingStoreBuffered, NSMakeRect, NSViewWidthSizable,
    )
    from Foundation import NSObject, NSIndexSet
    from PyObjCTools import AppHelper

    from .config import load_config, update_config
    from .dictionary import load_terms, load_corrections
    from .openrouter import (
        DEFAULT_CHAT_MODEL, DEFAULT_STT_MODEL, audio_model_ids, fetch_models,
        get_api_key, text_model_ids, transcription_model_ids,
    )

    CONTENT_H = WINDOW_H - 60  # rough usable height inside a tab view

    def make_label(text, x, y, w=150, h=18):
        tf = NSTextField.alloc().initWithFrame_(NSMakeRect(x, y, w, h))
        tf.setStringValue_(text)
        tf.setBezeled_(False)
        tf.setDrawsBackground_(False)
        tf.setEditable_(False)
        tf.setSelectable_(False)
        return tf

    def make_text_scroll(x, y, w, h, editable=True, font_size=12):
        scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(x, y, w, h))
        scroll.setHasVerticalScroller_(True)
        scroll.setBorderType_(1)  # NSLineBorder
        tv = NSTextView.alloc().initWithFrame_(
            NSMakeRect(0, 0, scroll.contentSize().width, scroll.contentSize().height))
        tv.setRichText_(False)
        tv.setFont_(NSFont.fontWithName_size_("Menlo", font_size))
        tv.setEditable_(editable)
        tv.setAutoresizingMask_(NSViewWidthSizable)
        scroll.setDocumentView_(tv)
        return scroll, tv

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

            tabs = NSTabView.alloc().initWithFrame_(
                NSMakeRect(10, 10, WINDOW_W - 20, WINDOW_H - 20))
            self.window.contentView().addSubview_(tabs)
            self._build_general_tab(tabs)
            self._build_prompt_tab(tabs)
            self._build_dictionary_tab(tabs)
            self._build_history_tab(tabs)

        _CONTEXT_TOGGLES = (
            ("enabled", "Context providers (master switch)"),
            ("app_info", "Frontmost app & window title"),
            ("text_before_cursor", "Text before cursor (input field)"),
            ("visible_text", "Visible text on screen (citations)"),
            ("browser", "Browser page (title & URL)"),
            ("vscode", "VS Code workspace files"),
            ("finder", "Finder selection & window"),
        )

        def _build_prompt_tab(self, tabs):
            v = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, WINDOW_W - 20, CONTENT_H))

            v.addSubview_(make_label("Share with the formatting model:",
                                     20, CONTENT_H - 34, w=400))
            self._ctx_boxes = {}
            for i, (key, title) in enumerate(self._CONTEXT_TOGGLES):
                col, row = divmod(i, 4)
                cb = NSButton.alloc().initWithFrame_(
                    NSMakeRect(20 + col * 290, CONTENT_H - 66 - row * 26, 280, 22))
                cb.setButtonType_(3)  # NSSwitchButton
                cb.setTitle_(title)
                cb.setState_(1)
                v.addSubview_(cb)
                self._ctx_boxes[key] = cb

            hint = make_label("Off = never read, never leaves this Mac.",
                              20, CONTENT_H - 178, w=500)
            hint.setFont_(NSFont.systemFontOfSize_(11))
            hint.setTextColor_(NSColor.secondaryLabelColor())
            v.addSubview_(hint)

            self.answer_checkbox = NSButton.alloc().initWithFrame_(
                NSMakeRect(20, CONTENT_H - 208, 420, 22))
            self.answer_checkbox.setButtonType_(3)  # NSSwitchButton
            self.answer_checkbox.setTitle_(
                "Answer obvious questions from context (instead of transcribing)")
            v.addSubview_(self.answer_checkbox)
            ahint = make_label("Off = always transcribe exactly what you said.",
                               20, CONTENT_H - 232, w=500)
            ahint.setFont_(NSFont.systemFontOfSize_(11))
            ahint.setTextColor_(NSColor.secondaryLabelColor())
            v.addSubview_(ahint)

            self.audio_checkbox = NSButton.alloc().initWithFrame_(
                NSMakeRect(20, CONTENT_H - 262, 480, 22))
            self.audio_checkbox.setButtonType_(3)  # NSSwitchButton
            self.audio_checkbox.setTitle_(
                "Also send the audio to the formatter (better recovery from bad transcription)")
            v.addSubview_(self.audio_checkbox)
            ahint2 = make_label("Costs a little more; needs an audio-capable model (e.g. gemini-2.5-flash).",
                                20, CONTENT_H - 286, w=500)
            ahint2.setFont_(NSFont.systemFontOfSize_(11))
            ahint2.setTextColor_(NSColor.secondaryLabelColor())
            v.addSubview_(ahint2)

            v.addSubview_(make_label("System prompt template", 20, CONTENT_H - 316, w=300))
            pscroll, self.prompt_text = make_text_scroll(
                20, 76, WINDOW_W - 60, CONTENT_H - 396, font_size=11)
            v.addSubview_(pscroll)
            phint = make_label("Placeholders:  {{mode_rules}}   {{dictionary}}   {{corrections}}   "
                               "{{context_block}}   {{context_rules}}",
                               20, 52, w=560)
            phint.setFont_(NSFont.systemFontOfSize_(10))
            phint.setTextColor_(NSColor.secondaryLabelColor())
            v.addSubview_(phint)

            sbtn = NSButton.alloc().initWithFrame_(NSMakeRect(20, 14, 120, 28))
            sbtn.setTitle_("Save prompt")
            sbtn.setBezelStyle_(1)
            sbtn.setTarget_(self)
            sbtn.setAction_("savePrompt:")
            v.addSubview_(sbtn)
            rbtn = NSButton.alloc().initWithFrame_(NSMakeRect(152, 14, 150, 28))
            rbtn.setTitle_("Reset to default")
            rbtn.setBezelStyle_(1)
            rbtn.setTarget_(self)
            rbtn.setAction_("resetPrompt:")
            v.addSubview_(rbtn)
            self.prompt_status = make_label("", 320, 18, w=260)
            self.prompt_status.setFont_(NSFont.systemFontOfSize_(11))
            self.prompt_status.setTextColor_(NSColor.secondaryLabelColor())
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

        def _build_general_tab(self, tabs):
            v = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, WINDOW_W - 20, CONTENT_H))
            y = CONTENT_H - 40

            v.addSubview_(make_label("STT backend", 20, y))
            self.backend_popup = NSPopUpButton.alloc().initWithFrame_pullsDown_(
                NSMakeRect(180, y - 3, 180, 26), False)
            self.backend_popup.addItemsWithTitles_(["mlx", "openrouter"])
            self.backend_popup.setTarget_(self)
            self.backend_popup.setAction_("backendChanged:")
            v.addSubview_(self.backend_popup)
            y -= 40

            v.addSubview_(make_label("STT model", 20, y))
            self.stt_model_combo = NSComboBox.alloc().initWithFrame_(
                NSMakeRect(180, y - 3, 240, 26))
            v.addSubview_(self.stt_model_combo)
            v.addSubview_(make_label("Languages", 428, y, w=60))
            self.lang_field = NSTextField.alloc().initWithFrame_(
                NSMakeRect(492, y - 3, 88, 24))
            self.lang_field.setPlaceholderString_("en, uk")
            self.lang_field.setToolTip_("comma-separated, empty = auto-detect")
            v.addSubview_(self.lang_field)
            y -= 40

            v.addSubview_(make_label("Formatter model", 20, y))
            self.fmt_model_combo = NSComboBox.alloc().initWithFrame_(
                NSMakeRect(180, y - 3, 360, 26))
            v.addSubview_(self.fmt_model_combo)
            y -= 40

            v.addSubview_(make_label("OpenRouter API key", 20, y, w=160))
            self.key_field = NSSecureTextField.alloc().initWithFrame_(
                NSMakeRect(180, y - 3, 360, 24))
            v.addSubview_(self.key_field)
            y -= 40

            v.addSubview_(make_label("Bubble style", 20, y))
            self.bubble_popup = NSPopUpButton.alloc().initWithFrame_pullsDown_(
                NSMakeRect(180, y - 3, 90, 26), False)
            self.bubble_popup.addItemsWithTitles_(["notch", "corner"])
            v.addSubview_(self.bubble_popup)
            v.addSubview_(make_label("(restart)", 280, y, w=65))
            v.addSubview_(make_label("Hold key", 350, y, w=70))
            self.holdkey_popup = NSPopUpButton.alloc().initWithFrame_pullsDown_(
                NSMakeRect(430, y - 3, 140, 26), False)
            self.holdkey_popup.addItemsWithTitles_(
                ["fn", "right_option", "right_command", "f5"])
            v.addSubview_(self.holdkey_popup)
            y -= 38

            v.addSubview_(make_label("Input sensitivity", 20, y))
            from AppKit import NSSlider
            self.sens_slider = NSSlider.alloc().initWithFrame_(
                NSMakeRect(180, y - 3, 220, 24))
            self.sens_slider.setMinValue_(0.5)
            self.sens_slider.setMaxValue_(2.5)
            self.sens_slider.setDoubleValue_(1.0)
            self.sens_slider.setTarget_(self)
            self.sens_slider.setAction_("sensitivityChanged:")
            v.addSubview_(self.sens_slider)
            self.sens_label = make_label("1.0", 410, y, w=50)
            v.addSubview_(self.sens_label)
            y -= 38

            self.llm_checkbox = NSButton.alloc().initWithFrame_(
                NSMakeRect(180, y, 400, 22))
            self.llm_checkbox.setButtonType_(3)  # NSSwitchButton
            self.llm_checkbox.setTitle_(
                "Format with LLM (uncheck for fastest raw insert)")
            v.addSubview_(self.llm_checkbox)
            y -= 30

            self.fast_checkbox = NSButton.alloc().initWithFrame_(
                NSMakeRect(180, y, 400, 22))
            self.fast_checkbox.setButtonType_(3)  # NSSwitchButton
            self.fast_checkbox.setTitle_(
                "Fast mode (skip LLM cleanup for short dictations)")
            v.addSubview_(self.fast_checkbox)
            fhint = make_label("Short inserts become instant; corrections still apply.",
                               200, y - 20, w=380)
            from AppKit import NSFont, NSColor
            fhint.setFont_(NSFont.systemFontOfSize_(10))
            fhint.setTextColor_(NSColor.secondaryLabelColor())
            v.addSubview_(fhint)
            y -= 34

            save_btn = NSButton.alloc().initWithFrame_(NSMakeRect(180, y, 100, 28))
            save_btn.setTitle_("Save")
            save_btn.setBezelStyle_(1)  # NSBezelStyleRounded
            save_btn.setTarget_(self)
            save_btn.setAction_("saveGeneral:")
            v.addSubview_(save_btn)

            fetch_btn = NSButton.alloc().initWithFrame_(NSMakeRect(300, y, 140, 28))
            fetch_btn.setTitle_("Fetch models")
            fetch_btn.setBezelStyle_(1)
            fetch_btn.setTarget_(self)
            fetch_btn.setAction_("refreshModels:")
            v.addSubview_(fetch_btn)
            y -= 35

            self.status_label = make_label("", 180, y, w=400, h=30)
            self.status_label.setFont_(NSFont.systemFontOfSize_(11))
            self.status_label.setTextColor_(NSColor.secondaryLabelColor())
            v.addSubview_(self.status_label)

            item = NSTabViewItem.alloc().initWithIdentifier_("general")
            item.setLabel_("General")
            item.setView_(v)
            tabs.addTabViewItem_(item)

        def _make_table(self, columns):
            """Small editable cell-based table; columns = [(ident, title, width)]."""
            scroll = NSScrollView.alloc().init()
            scroll.setHasVerticalScroller_(True)
            scroll.setBorderType_(1)
            table = NSTableView.alloc().initWithFrame_(NSMakeRect(0, 0, 100, 100))
            for ident, title, width in columns:
                col = NSTableColumn.alloc().initWithIdentifier_(ident)
                col.headerCell().setStringValue_(title)
                col.setWidth_(width)
                col.setEditable_(True)
                table.addTableColumn_(col)
            table.setDataSource_(self)
            table.setDelegate_(self)
            scroll.setDocumentView_(table)
            return scroll, table

        def _build_dictionary_tab(self, tabs):
            v = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, WINDOW_W - 20, CONTENT_H))
            paths = self.app_controller.cfg["paths"]

            v.addSubview_(make_label("TERMS (dictionary.txt)", 20, CONTENT_H - 30, w=400))
            tscroll, self.terms_table = self._make_table(
                [("term", "Term", WINDOW_W - 70)])
            tscroll.setFrame_(NSMakeRect(20, CONTENT_H - 205, WINDOW_W - 60, 170))
            v.addSubview_(tscroll)
            for title, action, x in (("+", "addTerm:", 20), ("−", "removeTerm:", 64)):
                btn = NSButton.alloc().initWithFrame_(NSMakeRect(x, CONTENT_H - 238, 40, 26))
                btn.setTitle_(title)
                btn.setBezelStyle_(1)
                btn.setTarget_(self)
                btn.setAction_(action)
                v.addSubview_(btn)
            tsbtn = NSButton.alloc().initWithFrame_(
                NSMakeRect(WINDOW_W - 180, CONTENT_H - 238, 140, 26))
            tsbtn.setTitle_("Save terms")
            tsbtn.setBezelStyle_(1)
            tsbtn.setTarget_(self)
            tsbtn.setAction_("saveTerms:")
            v.addSubview_(tsbtn)

            v.addSubview_(make_label("CORRECTIONS (corrections.tsv)", 20, CONTENT_H - 268, w=400))
            cscroll, self.corr_table = self._make_table(
                [("wrong", "Wrong", 265), ("right", "Right", 265)])
            cscroll.setFrame_(NSMakeRect(20, CONTENT_H - 390, WINDOW_W - 60, 117))
            v.addSubview_(cscroll)
            for title, action, x in (("+", "addCorrection:", 20), ("−", "removeCorrection:", 64)):
                btn = NSButton.alloc().initWithFrame_(NSMakeRect(x, CONTENT_H - 423, 40, 26))
                btn.setTitle_(title)
                btn.setBezelStyle_(1)
                btn.setTarget_(self)
                btn.setAction_(action)
                v.addSubview_(btn)
            csbtn = NSButton.alloc().initWithFrame_(
                NSMakeRect(WINDOW_W - 180, CONTENT_H - 423, 140, 26))
            csbtn.setTitle_("Save corrections")
            csbtn.setBezelStyle_(1)
            csbtn.setTarget_(self)
            csbtn.setAction_("saveCorrections:")
            v.addSubview_(csbtn)
            self._paths = paths

            item = NSTabViewItem.alloc().initWithIdentifier_("dictionary")
            item.setLabel_("Dictionary")
            item.setView_(v)
            tabs.addTabViewItem_(item)

        def _build_history_tab(self, tabs):
            v = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, WINDOW_W - 20, CONTENT_H))

            cbtn = NSButton.alloc().initWithFrame_(NSMakeRect(300, CONTENT_H - 35, 130, 26))
            cbtn.setTitle_("Check for edits")
            cbtn.setBezelStyle_(1)
            cbtn.setTarget_(self)
            cbtn.setAction_("checkForEdits:")
            v.addSubview_(cbtn)

            rbtn = NSButton.alloc().initWithFrame_(NSMakeRect(440, CONTENT_H - 35, 100, 26))
            rbtn.setTitle_("Refresh")
            rbtn.setBezelStyle_(1)
            rbtn.setTarget_(self)
            rbtn.setAction_("refreshHistory:")
            v.addSubview_(rbtn)

            scroll = NSScrollView.alloc().initWithFrame_(
                NSMakeRect(20, 250, WINDOW_W - 60, CONTENT_H - 295))
            scroll.setHasVerticalScroller_(True)
            scroll.setBorderType_(1)
            self.table = NSTableView.alloc().initWithFrame_(scroll.bounds())
            for ident, title, width in (("time", "Time", 130),
                                        ("app", "App", 100),
                                        ("text", "Raw → Final", 310)):
                col = NSTableColumn.alloc().initWithIdentifier_(ident)
                col.headerCell().setStringValue_(title)
                col.setWidth_(width)
                col.setMinWidth_(60)
                self.table.addTableColumn_(col)
            # Raw → Final soaks up extra width; columns stay user-resizable.
            self.table.setColumnAutoresizingStyle_(4)  # NSTableViewLastColumnOnlyAutoresizingStyle
            self.table.setDataSource_(self)
            self.table.setDelegate_(self)
            scroll.setDocumentView_(self.table)
            v.addSubview_(scroll)

            dscroll, self.detail_text = make_text_scroll(20, 160, WINDOW_W - 60, 80,
                                                         editable=False, font_size=10)
            v.addSubview_(dscroll)

            v.addSubview_(make_label("Suggestions (from your edits)", 20, 132, w=300))
            sscroll = NSScrollView.alloc().initWithFrame_(
                NSMakeRect(20, 52, WINDOW_W - 60, 76))
            sscroll.setHasVerticalScroller_(True)
            sscroll.setBorderType_(1)
            self.sug_table = NSTableView.alloc().initWithFrame_(sscroll.bounds())
            for ident, title, width in (("wrong", "Wrong", 200),
                                        ("right", "Right", 200),
                                        ("count", "Count", 45),
                                        ("app", "Last app", 95)):
                col = NSTableColumn.alloc().initWithIdentifier_(ident)
                col.headerCell().setStringValue_(title)
                col.setWidth_(width)
                self.sug_table.addTableColumn_(col)
            self.sug_table.setDataSource_(self)
            self.sug_table.setDelegate_(self)
            sscroll.setDocumentView_(self.sug_table)
            v.addSubview_(sscroll)

            for title, action, x in (("Add to corrections", "addToCorrections:", 20),
                                     ("Add to dictionary", "addToDictionary:", 170),
                                     ("Dismiss", "dismissSuggestion:", 320)):
                btn = NSButton.alloc().initWithFrame_(NSMakeRect(x, 16, 140, 28))
                btn.setTitle_(title)
                btn.setBezelStyle_(1)
                btn.setTarget_(self)
                btn.setAction_(action)
                v.addSubview_(btn)

            item = NSTabViewItem.alloc().initWithIdentifier_("history")
            item.setLabel_("History")
            item.setView_(v)
            tabs.addTabViewItem_(item)

        # -- loading ---------------------------------------------------------

        def _load_general(self):
            cfg = self.app_controller.cfg
            stt = cfg.get("stt", {})
            backend = stt.get("backend", "mlx")
            self.backend_popup.selectItemWithTitle_(
                backend if backend in ("mlx", "openrouter") else "mlx")
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
            self.llm_checkbox.setState_(
                1 if cfg.get("formatting", {}).get("enabled", True) else 0)
            self.fast_checkbox.setState_(
                1 if cfg.get("formatting", {}).get("fast_mode", False) else 0)

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
            records = []
            try:
                lines = Path(self.app_controller.cfg["paths"]["history"]) \
                    .read_text(encoding="utf-8").splitlines()
                for line in reversed(lines[-500:]):
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
            except FileNotFoundError:
                pass
            self._records = records
            self.table.reloadData()

        # -- actions (ObjC selectors) ---------------------------------------

        def backendChanged_(self, sender):
            self._load_stt_model_value()

        def sensitivityChanged_(self, sender):
            self.sens_label.setStringValue_(f"{self.sens_slider.doubleValue():.1f}")

        def saveGeneral_(self, sender):
            from dictate_core.stt import validate_languages
            backend = self.backend_popup.titleOfSelectedItem()
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
                           "sensitivity": round(self.sens_slider.doubleValue(), 1)},
                "hotkey": {"hold_key": self.holdkey_popup.titleOfSelectedItem()},
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
            text = f"{rec.get('raw', '')} → {rec.get('final', '')}"
            return text if len(text) <= 90 else text[:87] + "…"

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
                self.detail_text.setString_("")

        def _render_detail(self, rec):
            from .formatter import render_context_block
            text = f"RAW:\n{rec.get('raw', '')}\n\nFINAL:\n{rec.get('final', '')}"
            ctx = rec.get("context") or {}
            if ctx:
                text += f"\n\nCONTEXT:\n{render_context_block(ctx)}"
            return text

        # -- window delegate -------------------------------------------------

        def windowWillClose_(self, notification):
            # Accessory app: with no key window left, macOS returns focus to the
            # previously active app on its own.
            pass

        # -- public -----------------------------------------------------------

        def show(self):
            NSApp.activateIgnoringOtherApps_(True)
            self.window.makeKeyAndOrderFront_(None)

    return SettingsController.alloc().initWithAppController_(app_controller)
