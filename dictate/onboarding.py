"""Onboarding wizard (v2): branded 680x480 window with a dark sidebar.

7 pages: Welcome → Permissions → Hold key → OpenRouter key → Formatting
choice → Try it → Done. Shown on first run ([app] onboarded not set) and
from the menu ("Welcome / Setup…"). ObjC classes are defined once per
process; the window activates the app while open (accessory policy resumes
on close).
"""

import logging
import threading

log = logging.getLogger(__name__)

WINDOW_W, WINDOW_H = 680.0, 480.0
SIDEBAR_W = 220.0
CONTENT_X = SIDEBAR_W + 24
CONTENT_W = WINDOW_W - SIDEBAR_W - 48  # 412 usable
N_PAGES = 7

_controller_class = None

KEY_NAMES = {"fn": "fn", "right_option": "Right ⌥",
             "right_command": "Right ⌘", "f5": "F5"}


def _class():
    """Build (once) the ObjC onboarding controller class; class name is global."""
    global _controller_class
    if _controller_class is not None:
        return _controller_class

    import math
    import objc
    from AppKit import (
        NSApp, NSWindow, NSView, NSTextField, NSButton, NSFont, NSColor,
        NSBezierPath, NSImage, NSGradient, NSWindowStyleMaskTitled,
        NSWindowStyleMaskClosable, NSBackingStoreBuffered, NSScrollView,
        NSTextView, NSSecureTextField, NSPopUpButton, NSFontAttributeName,
        NSForegroundColorAttributeName, CALayer, CABasicAnimation,
    )
    from Foundation import NSObject, NSMakeRect, NSMakePoint, NSDictionary, NSString
    from Quartz import CGColorCreateGenericRGB, CGSizeMake
    from PyObjCTools import AppHelper

    from .config import PROJECT_ROOT
    from .permissions import (
        DEEP_LINKS, TITLES, check_all, granted, open_settings_page,
    )

    def rgb(r, g, b, a=1.0):
        return NSColor.colorWithCalibratedRed_green_blue_alpha_(r, g, b, a)

    ACCENT = rgb(1.0, 0.45, 0.15)
    TITLE_COLOR = rgb(0.10, 0.10, 0.12)
    BODY_COLOR = rgb(0.25, 0.25, 0.28)
    HINT_COLOR = rgb(0.52, 0.52, 0.56)

    PERM_ORDER = ("microphone", "input_monitoring", "accessibility")

    def label(text, x, y, w, h=18, size=13, bold=False, color=None, wrap=True,
              align="left"):
        tf = NSTextField.alloc().initWithFrame_(NSMakeRect(x, y, w, h))
        tf.setStringValue_(text)
        tf.setBezeled_(False)
        tf.setDrawsBackground_(False)
        tf.setEditable_(False)
        tf.setSelectable_(False)
        if wrap:
            tf.setLineBreakMode_(0)
            tf.setMaximumNumberOfLines_(0)
            tf.setPreferredMaxLayoutWidth_(w)
        tf.setFont_(NSFont.boldSystemFontOfSize_(size) if bold
                    else NSFont.systemFontOfSize_(size))
        if color is not None:
            tf.setTextColor_(color)
        if align == "center":
            tf.setAlignment_(1)
        return tf

    def chakra_image(size):
        """icon_A via the app icns (bundle resource or dev file)."""
        from AppKit import NSBundle
        path = NSBundle.mainBundle().pathForResource_ofType_("golos", "icns")
        if path is None:
            path = str(PROJECT_ROOT / "golos.icns")
        img = NSImage.alloc().initWithContentsOfFile_(path)
        if img is not None:
            img.setSize_((size, size))
        return img

    def sf_symbol(name, size, color):
        """Tinted SF Symbol, or None."""
        img = NSImage.imageWithSystemSymbolName_accessibilityDescription_(name, "golos")
        if img is None:
            return None
        from AppKit import NSImageSymbolConfiguration
        cfg = NSImageSymbolConfiguration.configurationWithPaletteColors_([color])
        cfg2 = cfg.configurationByApplyingConfiguration_(
            NSImageSymbolConfiguration.configurationWithPointSize_weight_(size, 5))
        img = img.imageWithSymbolConfiguration_(cfg2)
        return img

    class SidebarView(NSView):
        _page_index = 0

        def drawRect_(self, rect):
            grad = NSGradient.alloc().initWithStartingColor_endingColor_(
                rgb(0.07, 0.09, 0.18), rgb(0.04, 0.05, 0.11))
            grad.drawInRect_angle_(self.bounds(), -90)
            # faint chakra watermark behind the icon area
            img = chakra_image(300)
            if img is not None:
                img.drawInRect_fromRect_operation_fraction_(
                    NSMakeRect((SIDEBAR_W - 300) / 2, 210, 300, 300),
                    ((0, 0), (0, 0)), 0, 0.07)  # 0 = NSCompositingOperationSourceOver
            # page dots
            for i in range(N_PAGES):
                x = (SIDEBAR_W - (N_PAGES * 16)) / 2 + i * 16
                if i == self._page_index:
                    ACCENT.set()
                else:
                    rgb(1, 1, 1, 0.3).set()
                NSBezierPath.bezierPathWithOvalInRect_(
                    NSMakeRect(x, 34, 8, 8)).fill()

    class PadView(NSView):
        _active = False
        _text = "hold your key…"

        def drawRect_(self, rect):
            b = self.bounds()
            if self._active:
                ACCENT.set()
                NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                    b, 12, 12).fill()
                attrs = NSDictionary.dictionaryWithObjects_forKeys_(
                    [NSFont.boldSystemFontOfSize_(15), NSColor.whiteColor()],
                    [NSFontAttributeName, NSForegroundColorAttributeName])
            else:
                rgb(0.8, 0.8, 0.83).set()
                path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                    b, 12, 12)
                path.setLineWidth_(1.5)
                path.stroke()
                attrs = NSDictionary.dictionaryWithObjects_forKeys_(
                    [NSFont.systemFontOfSize_(14), HINT_COLOR],
                    [NSFontAttributeName, NSForegroundColorAttributeName])
            s = NSString.stringWithString_(self._text)
            size = s.sizeWithAttributes_(attrs)
            s.drawAtPoint_withAttributes_(
                NSMakePoint((b.size.width - size.width) / 2,
                            (b.size.height - size.height) / 2), attrs)

    class CardView(NSView):
        _title = ""
        _caption = ""
        _selected = False
        _on_select = None

        def drawRect_(self, rect):
            b = self.bounds()
            if self._selected:
                ACCENT.set()
                path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                    b, 12, 12)
                path.setLineWidth_(2.5)
                path.stroke()
                rgb(1.0, 0.45, 0.15, 0.08).set()
                NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                    b, 12, 12).fill()
            else:
                rgb(0.8, 0.8, 0.83).set()
                path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                    b, 12, 12)
                path.setLineWidth_(1.5)
                path.stroke()
            tattrs = NSDictionary.dictionaryWithObjects_forKeys_(
                [NSFont.boldSystemFontOfSize_(14), TITLE_COLOR],
                [NSFontAttributeName, NSForegroundColorAttributeName])
            NSString.stringWithString_(self._title).drawAtPoint_withAttributes_(
                NSMakePoint(14, b.size.height - 34), tattrs)
            cattrs = NSDictionary.dictionaryWithObjects_forKeys_(
                [NSFont.systemFontOfSize_(11), BODY_COLOR],
                [NSFontAttributeName, NSForegroundColorAttributeName])
            NSString.stringWithString_(self._caption).drawInRect_withAttributes_(
                NSMakeRect(14, 14, b.size.width - 28, b.size.height - 52), cattrs)

        def mouseUp_(self, event):
            if self._on_select is not None:
                self._on_select()

    class OnboardingController(NSObject):
        def initWithAppController_(self, ctl):
            self = objc.super(OnboardingController, self).init()
            if self is None:
                return None
            self.app_controller = ctl
            self._page = 0
            self._perm_labels = {}
            self._perm_timer = None
            self._try_field = None
            self._try_status = None
            self._try_dot = None
            self._fmt_ai = None
            self._fmt_raw = None
            self.window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
                NSMakeRect(0, 0, WINDOW_W, WINDOW_H),
                NSWindowStyleMaskTitled | NSWindowStyleMaskClosable,
                NSBackingStoreBuffered, False)
            self.window.setTitle_("Welcome to golos")
            self.window.setReleasedWhenClosed_(False)
            self.window.center()
            self._build_chrome()
            self.showPage_(0)
            return self

        # -- chrome: sidebar + content area + nav buttons ---------------------

        def _build_chrome(self):
            root = self.window.contentView()
            self.sidebar = SidebarView.alloc().initWithFrame_(
                NSMakeRect(0, 0, SIDEBAR_W, WINDOW_H))
            root.addSubview_(self.sidebar)
            img = chakra_image(96)
            if img is not None:
                from AppKit import NSImageView
                iv = NSImageView.alloc().initWithFrame_(NSMakeRect(62, 286, 96, 96))
                iv.setImage_(img)
                self.sidebar.addSubview_(iv)
            self.sidebar.addSubview_(label(
                "golos", 0, 236, SIDEBAR_W, 30, 22, True,
                NSColor.whiteColor(), align="center"))
            self.sidebar.addSubview_(label(
                "Talk to your Mac.\nIt types.", 20, 196, SIDEBAR_W - 40, 36, 12,
                False, rgb(1, 1, 1, 0.6), align="center"))

            self.page_area = NSView.alloc().initWithFrame_(
                NSMakeRect(SIDEBAR_W, 64, WINDOW_W - SIDEBAR_W, WINDOW_H - 64))
            root.addSubview_(self.page_area)

            self.back_btn = self._nav_button("Back", 0, "goBack:")
            self.back_btn.setFrameOrigin_(NSMakePoint(WINDOW_W - 246, 16))
            root.addSubview_(self.back_btn)
            self.next_btn = self._nav_button("Continue", 1, "goNext:")
            self.next_btn.setFrameOrigin_(NSMakePoint(WINDOW_W - 140, 16))
            root.addSubview_(self.next_btn)

        def _nav_button(self, title, style, action):
            b = NSButton.alloc().initWithFrame_(NSMakeRect(0, 0, 96, 32))
            b.setBezelStyle_(1)  # rounded
            if style == 1:  # primary accent
                self._accent_button = b
                self._set_next_title(title)
                b.setWantsLayer_(True)
                b.layer().setBackgroundColor_(
                    CGColorCreateGenericRGB(1.0, 0.45, 0.15, 1.0))
                b.layer().setCornerRadius_(8)
                b.setBordered_(False)
            else:
                b.setTitle_(title)
            b.setTarget_(self)
            b.setAction_(action)
            return b

        def _set_next_title(self, title):
            from Foundation import NSAttributedString
            attrs = NSDictionary.dictionaryWithObjects_forKeys_(
                [NSFont.boldSystemFontOfSize_(13), NSColor.whiteColor()],
                [NSFontAttributeName, NSForegroundColorAttributeName])
            self._accent_button.setAttributedTitle_(
                NSAttributedString.alloc().initWithString_attributes_(title, attrs))

        def _set_page(self, view):
            for sub in list(self.page_area.subviews()):
                sub.removeFromSuperview()
            view.setAlphaValue_(0.0)
            self.page_area.addSubview_(view)
            def fade(ctx):
                ctx.setDuration_(0.25)
                view.animator().setAlphaValue_(1.0)
            from AppKit import NSAnimationContext
            NSAnimationContext.runAnimationGroup_(fade)

        def showPage_(self, page):
            # leaving the Try-it page: stop state mirroring; leaving the Hold-key
            # page: stop the test pad handler
            if self.app_controller.on_state_change is not None:
                self.app_controller.on_state_change = None
            if self.app_controller.hotkey_test_handler is not None:
                self.app_controller.hotkey_test_handler = None
            self._page = page
            builders = (self._page_welcome, self._page_permissions,
                        self._page_fnkey, self._page_apikey,
                        self._page_formatting, self._page_tryit,
                        self._page_done)
            if self._perm_timer is not None:
                self._perm_timer.invalidate()
                self._perm_timer = None
            self._set_page(builders[page]())
            self.back_btn.setEnabled_(page > 0)
            self._set_next_title("Finish" if page == N_PAGES - 1 else "Continue")
            self.sidebar._page_index = page
            self.sidebar.setNeedsDisplay_(True)
            if page == 1:
                from Foundation import NSTimer
                self._perm_timer = NSTimer \
                    .scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                        2.0, self, "permTick:", None, True)
            if page == 2:
                self.app_controller.hotkey_test_handler = self._hotkey_test
            if page == 5 and self._try_field is not None:
                self.window.makeFirstResponder_(self._try_field)

        def goBack_(self, sender):
            if self._page > 0:
                self.showPage_(self._page - 1)

        def goNext_(self, sender):
            if self._page == 4:
                self._save_formatting_choice()
            if self._page < N_PAGES - 1:
                self.showPage_(self._page + 1)
            else:
                self._finish()

        # -- pages --------------------------------------------------------------

        def _page_welcome(self):
            v = NSView.alloc().initWithFrame_(self.page_area.bounds())
            v.addSubview_(label("Talk to your Mac. It types.", 24, 356, CONTENT_W, 26, 20, True, TITLE_COLOR))
            v.addSubview_(label("golos turns your voice into text, anywhere a cursor can blink.",
                                24, 326, CONTENT_W, 20, 13, False, BODY_COLOR))
            rows = [
                ("waveform", "Hold your key, speak, release —\ntext appears at the cursor."),
                ("sparkles", "AI cleans up wording, punctuation\nand builds real lists."),
                ("book", "It learns your names and terms\nas you correct them."),
            ]
            y = 240
            for sym, text in rows:
                img = sf_symbol(sym, 22, ACCENT)
                if img is not None:
                    from AppKit import NSImageView
                    iv = NSImageView.alloc().initWithFrame_(NSMakeRect(24, y, 26, 26))
                    iv.setImage_(img)
                    v.addSubview_(iv)
                v.addSubview_(label(text, 62, y - 6, CONTENT_W - 40, 40, 13, False, BODY_COLOR))
                y -= 62
            return v

        def _page_permissions(self):
            v = NSView.alloc().initWithFrame_(self.page_area.bounds())
            v.addSubview_(label("macOS needs three permissions", 24, 356, CONTENT_W, 24, 18, True, TITLE_COLOR))
            v.addSubview_(label("Grant each, then come back — this page updates live.",
                                24, 328, CONTENT_W, 18, 12, False, HINT_COLOR))
            y = 280
            self._perm_labels = {}
            for kind in PERM_ORDER:
                v.addSubview_(label(TITLES[kind], 24, y, 230, 20, 13, True, TITLE_COLOR))
                pill = label("…", 258, y, 84, 20, 11, True, NSColor.whiteColor(), align="center")
                pill.setDrawsBackground_(True)
                v.addSubview_(pill)
                self._perm_labels[kind] = pill
                ob = NSButton.alloc().initWithFrame_(NSMakeRect(352, y - 4, 110, 26))
                ob.setTitle_("Open Settings")
                ob.setBezelStyle_(1)
                ob.setTarget_(self)
                ob.setAction_(f"openPerm{len(self._perm_labels)}:")
                v.addSubview_(ob)
                y -= 52
            self._perm_warn = label("", 24, y - 4, CONTENT_W, 36, 12)
            self._perm_warn.setTextColor_(rgb(0.85, 0.5, 0.1))
            v.addSubview_(self._perm_warn)
            self._refresh_perms()
            return v

        def openPerm1_(self, sender):
            open_settings_page("microphone")

        def openPerm2_(self, sender):
            open_settings_page("input_monitoring")

        def openPerm3_(self, sender):
            open_settings_page("accessibility")

        def permTick_(self, timer):
            self._refresh_perms()

        def _refresh_perms(self):
            status = check_all()
            missing = []
            for kind, pill in self._perm_labels.items():
                ok = granted(status[kind])
                pill.setStringValue_("granted" if ok else "required")
                pill.setBackgroundColor_(
                    rgb(0.2, 0.75, 0.35) if ok else ACCENT)
                if not ok:
                    missing.append(TITLES[kind].split(" (")[0])
            self._perm_warn.setStringValue_(
                "" if not missing else
                "Missing: " + ", ".join(missing) +
                " — golos won't work fully until granted (you can still Continue).")

        # -- hold key ----------------------------------------------------------

        def _page_fnkey(self):
            v = NSView.alloc().initWithFrame_(self.page_area.bounds())
            v.addSubview_(label("Your hold-to-talk key", 24, 356, CONTENT_W, 24, 18, True, TITLE_COLOR))
            v.addSubview_(label("Pick what you'll hold while speaking. Anything is fine —\nfn (globe) is the classic.",
                                24, 320, CONTENT_W, 36, 12, False, HINT_COLOR))
            current = self.app_controller.cfg.get("hotkey", {}).get("hold_key", "fn")
            self.holdkey_popup = NSPopUpButton.alloc().initWithFrame_pullsDown_(
                NSMakeRect(24, 264, 220, 28), False)
            self.holdkey_popup.addItemsWithTitles_(
                ["fn", "right_option", "right_command", "f5"])
            self.holdkey_popup.selectItemWithTitle_(current)
            self.holdkey_popup.setTarget_(self)
            self.holdkey_popup.setAction_("holdkeyChanged:")
            v.addSubview_(self.holdkey_popup)

            self._fn_note = label(
                "Also set System Settings → Keyboard → “Press 🌐/fn key to” → “Do Nothing”,\n"
                "or macOS steals the fn key for its own action.",
                24, 218, CONTENT_W, 32, 12, False, HINT_COLOR)
            v.addSubview_(self._fn_note)
            self._fn_note.setHidden_(current != "fn")

            self._pad = PadView.alloc().initWithFrame_(
                NSMakeRect(24, 110, CONTENT_W, 84))
            self._pad._text = "hold your key…"
            v.addSubview_(self._pad)
            self._pad_status = label("test pad: hold the key and watch it light up",
                                     24, 82, CONTENT_W, 18, 12, False, HINT_COLOR)
            v.addSubview_(self._pad_status)
            return v

        def holdkeyChanged_(self, sender):
            key = self.holdkey_popup.titleOfSelectedItem()
            self._fn_note.setHidden_(key != "fn")
            try:
                from .config import update_config
                update_config({"hotkey": {"hold_key": key}})
                self.app_controller.apply_settings()  # live rebind
            except Exception as e:
                log.warning("Could not persist hold key: %s", e)

        def _hotkey_test(self, phase):
            if phase == "press":
                self._pad._active = True
                self._pad._text = "holding… ✓ detected"
            else:
                self._pad._active = False
                self._pad._text = "hold your key…"
            self._pad.setNeedsDisplay_(True)

        # -- api key -------------------------------------------------------------

        def _page_apikey(self):
            v = NSView.alloc().initWithFrame_(self.page_area.bounds())
            v.addSubview_(label("OpenRouter API key (optional)", 24, 356, CONTENT_W, 24, 18, True, TITLE_COLOR))
            v.addSubview_(label(
                "Enables cloud transcription and the AI formatting pass. "
                "Without it, local on-device Whisper works fully offline.",
                24, 322, CONTENT_W, 36, 12, False, HINT_COLOR))
            self._key_field = NSSecureTextField.alloc().initWithFrame_(
                NSMakeRect(24, 270, CONTENT_W, 26))
            self._key_field.setPlaceholderString_("sk-or-…")
            v.addSubview_(self._key_field)
            sbtn = NSButton.alloc().initWithFrame_(NSMakeRect(24, 220, 140, 30))
            sbtn.setTitle_("Save & validate")
            sbtn.setBezelStyle_(1)
            sbtn.setTarget_(self)
            sbtn.setAction_("saveKey:")
            v.addSubview_(sbtn)
            kbtn = NSButton.alloc().initWithFrame_(NSMakeRect(180, 220, 140, 30))
            kbtn.setTitle_("Skip for now")
            kbtn.setBezelStyle_(1)
            kbtn.setTarget_(self)
            kbtn.setAction_("goNext:")
            v.addSubview_(kbtn)
            self._key_status = label("", 24, 190, CONTENT_W, 20, 12)
            v.addSubview_(self._key_status)
            return v

        def saveKey_(self, sender):
            key = str(self._key_field.stringValue()).strip()
            if not key:
                self._key_status.setStringValue_("(empty — nothing saved)")
                return
            self._key_status.setStringValue_("Validating…")

            def work():
                try:
                    from .openrouter import fetch_models
                    fetch_models(key)
                except Exception as e:
                    AppHelper.callAfter(
                        self._key_status.setStringValue_, f"✗ invalid: {e}")
                else:
                    from .config import update_config
                    update_config({"openrouter": {"api_key": key}})
                    AppHelper.callAfter(self.app_controller.apply_settings)
                    AppHelper.callAfter(self._key_status.setStringValue_,
                                        "✓ saved and validated")

            threading.Thread(target=work, daemon=True).start()

        # -- formatting choice ------------------------------------------------

        def _page_formatting(self):
            v = NSView.alloc().initWithFrame_(self.page_area.bounds())
            v.addSubview_(label("How should golos treat your words?", 24, 356, CONTENT_W, 24, 18, True, TITLE_COLOR))
            v.addSubview_(label("Pick one — you can change it anytime in Settings.",
                                24, 328, CONTENT_W, 18, 12, False, HINT_COLOR))
            fmt_on = self.app_controller.cfg.get("formatting", {}).get("enabled", True)
            self._fmt_ai = CardView.alloc().initWithFrame_(NSMakeRect(24, 160, 194, 140))
            self._fmt_ai._title = "AI formatting"
            self._fmt_ai._caption = ("Cleaner text, real lists, citations from "
                                     "context. Adds 1–3 s per dictation.")
            self._fmt_ai._on_select = lambda: self._select_fmt(True)
            v.addSubview_(self._fmt_ai)
            self._fmt_raw = CardView.alloc().initWithFrame_(NSMakeRect(242, 160, 194, 140))
            self._fmt_raw._title = "Raw & instant"
            self._fmt_raw._caption = ("Exactly what you said, inserted as fast "
                                      "as possible. Nothing leaves the Mac.")
            self._fmt_raw._on_select = lambda: self._select_fmt(False)
            v.addSubview_(self._fmt_raw)
            self._select_fmt(fmt_on)
            v.addSubview_(label(
                "Short dictations (≤10 words) can skip the AI pass too — see Fast mode in Settings.",
                24, 116, CONTENT_W, 32, 12, False, HINT_COLOR))
            return v

        def _select_fmt(self, ai):
            self._fmt_ai._selected = ai
            self._fmt_raw._selected = not ai
            self._fmt_ai.setNeedsDisplay_(True)
            self._fmt_raw.setNeedsDisplay_(True)

        def _save_formatting_choice(self):
            try:
                from .config import update_config
                update_config({"formatting": {
                    "enabled": bool(self._fmt_ai._selected)}})
                self.app_controller.apply_settings()
            except Exception as e:
                log.warning("Could not persist formatting choice: %s", e)

        # -- try it ---------------------------------------------------------------

        _STATE_LABELS = {"recording": "listening…", "locked": "listening…",
                         "processing": "processing…", "success": "inserted ✓",
                         "idle": ""}

        def _page_tryit(self):
            v = NSView.alloc().initWithFrame_(self.page_area.bounds())
            v.addSubview_(label("Try it right here", 24, 356, CONTENT_W, 24, 18, True, TITLE_COLOR))
            # An ordinary editable text view: dictation inserts typed text into
            # whatever is frontmost+focused — while the wizard is frontmost,
            # that's this field. Multi-line paste works here too.
            scroll = NSScrollView.alloc().initWithFrame_(
                NSMakeRect(24, 216, CONTENT_W, 116))
            scroll.setHasVerticalScroller_(True)
            scroll.setBorderType_(1)
            self._try_field = NSTextView.alloc().initWithFrame_(
                NSMakeRect(0, 0, scroll.contentSize().width,
                           scroll.contentSize().height))
            self._try_field.setRichText_(False)
            self._try_field.setFont_(NSFont.systemFontOfSize_(14))
            scroll.setDocumentView_(self._try_field)
            v.addSubview_(scroll)

            self._try_dot = CALayer.layer()
            self._try_dot.setFrame_(NSMakeRect(26, 192, 10, 10))
            self._try_dot.setCornerRadius_(5)
            self._try_dot.setBackgroundColor_(CGColorCreateGenericRGB(0.9, 0.2, 0.2, 1.0))
            self._try_dot.setHidden_(True)
            v.setWantsLayer_(True)
            v.layer().addSublayer_(self._try_dot)
            self._try_status = label("", 44, 188, 300, 18, 12, False, HINT_COLOR)
            v.addSubview_(self._try_status)

            v.addSubview_(label(
                "1. Hold your key, say something, release — it should appear above.\n"
                "2. Press your key+Space, speak, press your key again to stop.\n"
                "Made a mistake? Esc cancels while recording.",
                24, 96, CONTENT_W, 64, 12, False, BODY_COLOR))
            self.app_controller.on_state_change = self._try_state_changed
            return v

        def _try_state_changed(self, state):
            if self._try_status is not None:
                self._try_status.setStringValue_(
                    self._STATE_LABELS.get(state, ""))
            if self._try_dot is not None:
                active = state in ("recording", "locked")
                self._try_dot.setHidden_(not active)
                self._try_dot.removeAnimationForKey_("pulse")
                if active:
                    anim = CABasicAnimation.animationWithKeyPath_("opacity")
                    anim.setFromValue_(1.0)
                    anim.setToValue_(0.25)
                    anim.setDuration_(0.7)
                    anim.setAutoreverses_(True)
                    anim.setRepeatCount_(1e9)
                    self._try_dot.addAnimation_forKey_(anim, "pulse")

        # -- done --------------------------------------------------------------

        def _page_done(self):
            v = NSView.alloc().initWithFrame_(self.page_area.bounds())
            key = self.app_controller.cfg.get("hotkey", {}).get("hold_key", "fn")
            key_name = KEY_NAMES.get(key, key)
            check = sf_symbol("checkmark.circle.fill", 56, rgb(0.2, 0.75, 0.35))
            if check is not None:
                from AppKit import NSImageView
                iv = NSImageView.alloc().initWithFrame_(NSMakeRect(24, 300, 60, 60))
                iv.setImage_(check)
                v.addSubview_(iv)
            v.addSubview_(label("You're set.", 96, 316, CONTENT_W - 72, 28, 20, True, TITLE_COLOR))
            v.addSubview_(label(
                f"Hold {key_name} anywhere and speak — your words appear.\n"
                "Find more in Settings → Prompt.",
                24, 240, CONTENT_W, 44, 13, False, BODY_COLOR))
            tbtn = NSButton.alloc().initWithFrame_(NSMakeRect(24, 180, 160, 30))
            tbtn.setTitle_("Test insertion")
            tbtn.setBezelStyle_(1)
            tbtn.setTarget_(self)
            tbtn.setAction_("testInsertion:")
            v.addSubview_(tbtn)
            self._test_status = label("", 196, 184, 240, 20, 12)
            v.addSubview_(self._test_status)
            return v

        def testInsertion_(self, sender):
            from .insert import insert_text
            ok = insert_text("✅ golos insertion test")
            self._test_status.setStringValue_(
                "Pasted at the cursor ✓" if ok else
                "Could not paste — check Accessibility permission.")

        # -- finish --------------------------------------------------------------

        def _finish(self):
            if self._perm_timer is not None:
                self._perm_timer.invalidate()
                self._perm_timer = None
            try:
                from .config import update_config
                update_config({"app": {"onboarded": True}})
            except Exception as e:
                log.warning("Could not persist onboarded flag: %s", e)
            self.window.close()

        def windowWillClose_(self, notification):
            if self._perm_timer is not None:
                self._perm_timer.invalidate()
                self._perm_timer = None
            if self.app_controller.on_state_change is not None:
                self.app_controller.on_state_change = None
            if self.app_controller.hotkey_test_handler is not None:
                self.app_controller.hotkey_test_handler = None
            # accessory app: focus returns to the previous app on its own

        def show(self):
            NSApp.activateIgnoringOtherApps_(True)
            self.window.makeKeyAndOrderFront_(None)

    _controller_class = OnboardingController
    return _controller_class


def show_onboarding(app_controller):
    """Create (once) and show the onboarding window."""
    ctl = getattr(app_controller, "_onboarding", None)
    if ctl is None:
        cls = _class()
        ctl = cls.alloc().initWithAppController_(app_controller)
        app_controller._onboarding = ctl
    ctl.show()
