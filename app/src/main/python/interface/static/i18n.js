/*
 * Prompt 956 - Persian-first presentation layer.
 *
 * Pure, DOM-free helpers: the Persian UI strings and a few deterministic
 * display-only conversions. Nothing here talks to the server, changes what
 * the runtime returns, or invents capabilities - the raw reply from
 * /api/message is always what the runtime produced; this file only decides
 * how fixed, known labels are shown to a Persian reader.
 *
 * Works in the WebView (attaches to window.FaUI) and under Node
 * (module.exports) so it can be unit-tested without a browser.
 */
(function (root) {
  "use strict";

  var STR = {
    appName: "دستیار هوشمند",
    online: "آنلاین · محلی",
    offline: "ارتباط قطع است",
    connecting: "در حال اتصال…",
    infoButton: "اطلاعات سیستم",
    close: "بستن",
    send: "ارسال",
    sending: "در حال ارسال…",
    thinking: "در حال پردازش…",
    inputPlaceholder: "پیام خود را بنویسید…",
    inputLabel: "پیام",
    conversationLabel: "گفتگو",
    greeting:
      "سلام! من دستیار شخصی شما هستم و روی همین دستگاه اجرا می‌شوم.\n" +
      "فعلاً می‌توانم گفتگوی ساده داشته باشم، چیزهایی را که به من یاد می‌دهید به خاطر بسپارم " +
      "و دستورهای AEL را اجرا کنم. توانایی‌های من به‌تدریج گسترش پیدا می‌کنند.\n" +
      "برای شروع یک پیام بنویسید.",
    hintsLabel: "نمونه‌هایی برای شروع",
    hintTeach: "یاد دادن یک مطلب",
    hintAsk: "پرسیدن از مطلب",
    hintTeachText: "TEACH sky IS the atmosphere above the earth",
    hintAskText: "ASK sky",
    errorNetwork: "ارتباط با سرور محلی برقرار نشد. لطفاً دوباره تلاش کنید.",
    errorServer: "خطایی در پردازش پیام رخ داد. لطفاً دوباره تلاش کنید.",
    errorTooLarge: "پیام بیش‌ازحد طولانی است. لطفاً آن را کوتاه‌تر کنید.",
    errorBadRequest: "درخواست نامعتبر بود. لطفاً دوباره تلاش کنید.",
    emptyReply: "پاسخی دریافت نشد.",
    panelTitle: "اطلاعات سیستم",
    footerNote: "بدون وابستگی به سرویس هوش مصنوعی خارجی · اینترنت فقط با اجازهٔ خودت",
    attach: "پیوست",
    attachLabel: "پیوست فایل متنی",
    attachReady: "فایل «{name}» خوانده شد ({n} نویسه) و در کادر پیام گذاشته شد. هنوز چیزی فرستاده نشده؛ بررسی کن و «ارسال» را بزن.",
    attachTooLarge: "این فایل بزرگ‌تر از ۲۰۰ کیلوبایت است؛ نخوانده شد و چیزی فرستاده نشد.",
    attachEmpty: "این فایل خالی است؛ چیزی خوانده نشد.",
    attachNotText: "این فایل متن UTF-8 نیست (فقط فایل متنی یا JSON پشتیبانی می‌شود)؛ نخوانده شد.",
    attachFailed: "خواندن فایل ناموفق بود؛ چیزی تغییر نکرد.",
    // Prompt 958: the phone's own buttons (they exist only inside the Android app). Every note says what really
    // happened and what did NOT: nothing is sent or imported by these buttons without the user's own next step.
    nativeBarLabel: "ابزارهای گوشی",
    voiceButton: "🎤 گفتار",
    voiceLabel: "گفتار به متن",
    modelButton: "📦 فایل مدل",
    modelLabel: "وارد کردن فایل مدل زبانی",
    voiceUnavailable: "گفتار روی این گوشی یا در این لحظه در دسترس نیست؛ چیزی تغییر نکرد.",
    voiceHeard: "متنِ شنیده‌شده ({n} نویسه) در کادر پیام گذاشته شد. هنوز چیزی فرستاده نشده؛ بررسی کن و «ارسال» را بزن.",
    voiceNothing: "چیزی شنیده نشد یا گفتار لغو شد؛ چیزی تغییر نکرد.",
    pickUnavailable: "پنجرهٔ انتخابِ فایل باز نشد؛ چیزی تغییر نکرد.",
    copyProgress: "در حال کپیِ «{name}» از گوشی: {done} از {total} ({percent}٪)",
    copyProgressUnknown: "در حال کپیِ «{name}» از گوشی: {done} کپی شد…",
    modelCopied: "فایل «{name}» ({size}) از گوشی کپی شد. حالا برنامه می‌پرسد که وارد کند یا نه؛ بدون «بله»ی خودت چیزی وارد نمی‌شود.",
    fileCopied: "فایل «{name}» ({size}) در پوشهٔ ورودیِ برنامه گذاشته شد.",
    importCommand: "مدل {name} را وارد کن",
    pickCancelled: "انتخابِ فایل لغو شد؛ چیزی تغییر نکرد.",
    pickBusy: "کپیِ فایلِ دیگری هنوز ادامه دارد؛ کمی صبر کن.",
    pickUnsupported: "این فایل مدلِ زبانی نیست؛ فقط فایل‌های «.task» و «.gguf» پذیرفته می‌شوند.",
    pickTooLargeModel: "این فایل از سقفِ مجاز (۸ گیگابایت) بزرگ‌تر است؛ چیزی کپی نشد.",
    pickTooLargeFile: "این فایل از سقفِ مجاز (۶۴ مگابایت) بزرگ‌تر است؛ چیزی کپی نشد.",
    pickNoSpace: "جای خالیِ کافی روی گوشی نیست؛ چیزی کپی نشد.",
    pickUnreadable: "فایل خوانده نشد (اندروید دسترسی نداد)؛ چیزی کپی نشد.",
    pickIoError: "هنگام کپی خطا رخ داد؛ فایلِ ناقص پاک شد.",
    pickSizeMismatch: "اندازهٔ فایلِ کپی‌شده با اصل یکی نبود؛ فایلِ ناقص پاک شد. دوباره امتحان کن.",
    pickEmpty: "فایل خالی بود؛ چیزی کپی نشد.",
    pickNoInbox: "پوشهٔ ورودیِ برنامه ساخته نشد؛ چیزی کپی نشد.",
    pickFailed: "کپیِ فایل ناموفق بود؛ چیزی تغییر نکرد.",
    answerCame: "جواب آمد",
    sharedMission: "متنی که از برنامهٔ دیگر فرستادی ({n} نویسه) گرفته شد. چون درخواستی منتظرِ جواب بود، همین را به چت دادم تا بررسی کند؛ چیزی نصب نمی‌شود مگر با «بله»ی خودت.",
    sharedReady: "متنی که از برنامهٔ دیگر فرستادی ({n} نویسه) در کادر پیام گذاشته شد. هنوز چیزی فرستاده نشده؛ بررسی کن و «ارسال» را بزن.",
    sharedTooLong: "متنِ فرستاده‌شده ({n} نویسه) برای کادر پیام زیادی بلند است؛ فقط در پوشهٔ ورودی ذخیره شد و چیزی فرستاده نشد.",
    sharedCut: "متنِ فرستاده‌شده خیلی بلند بود ({n} نویسه) و فقط بخشِ اولش ذخیره شد؛ چیزی فرستاده نشد.",
    sharedNotText: "متنِ فرستاده‌شده نویسهٔ نامعتبر داشت؛ ذخیره شد ولی در کادر پیام نگذاشتمش و چیزی فرستاده نشد.",
    sharedEmpty: "متنِ فرستاده‌شده خالی بود؛ چیزی ذخیره نشد.",
    sharedFailed: "ذخیرهٔ متنِ فرستاده‌شده ناموفق بود؛ چیزی تغییر نکرد.",
    longMessage: "… (پیام بلند است: {n} نویسه. کوتاه‌شدن فقط برای نمایش است؛ متن کامل فرستاده شد.)",
    version: "نسخه",
    metrics: {
      "m-version": "نسخهٔ دستیار",
      "m-knowledge": "مطالب آموخته‌شده",
      "m-concepts": "مفاهیم",
      "m-skills": "مهارت‌ها",
      "m-capabilities": "قابلیت‌ها",
      "m-installed": "ارتقاهای نصب‌شده",
      "m-failed": "ارتقاهای ناموفق",
      "m-learning-events": "رویدادهای یادگیری",
      "m-errors": "خطاهای ثبت‌شده",
      "m-status": "وضعیت سیستم"
    },
    healthTitle: "سلامت سیستم",
    healthEmpty: "هنوز داده‌ای برای سلامت سیستم نیست.",
    healthChecking: "در حال بررسی…",
    upgradesTitle: "تاریخچهٔ ارتقاها",
    upgradesEmpty: "هنوز ارتقایی انجام نشده است."
  };

  // Display labels for the fixed status words the backend emits.
  var STATUS = {
    healthy: "سالم",
    warning: "هشدار",
    degraded: "ناقص",
    error: "خطا",
    installed: "نصب‌شده",
    failed: "ناموفق",
    pending: "در انتظار",
    unknown: "نامشخص"
  };

  // Fixed templates the runtime emits in English. Each rule translates only
  // the template wording; names, quotes and any text the user or the runtime
  // supplied inside it are carried over unchanged. A reply that matches no
  // rule is shown exactly as the runtime produced it.
  var REPLY_RULES = [
    [/^Say something and I'll try to respond\.$/g, "چیزی بنویسید تا پاسخ دهم."],
    [/^Hello! I'm a very early version of myself right now - I don't know much yet\. Teach me things using AEL and I'll remember them\.$/g,
      "سلام! من هنوز نسخهٔ خیلی اولیهٔ خودم هستم و چیز زیادی نمی‌دانم. با AEL به من چیز یاد بدهید تا به خاطر بسپارم."],
    // AEL results
    [/^Learned concept '(.*)'\.$/gm, "مفهوم «$1» آموخته شد."],
    [/^Skill '(.*)' installed\.$/gm, "مهارت «$1» نصب شد."],
    [/^I don't know anything about '(.*)' yet\.$/gm, "هنوز چیزی دربارهٔ «$1» نمی‌دانم."],
    [/\(no description yet\)/g, "(هنوز توضیحی ثبت نشده)"],
    [/^Related '(.*)' -> '(.*)' as '(.*)'\./gm, "«$1» و «$2» با رابطهٔ «$3» به هم مرتبط شدند."],
    [/ \(Already known - no duplicate stored\.\)/g, " (از قبل ثبت شده بود؛ تکراری ذخیره نشد.)"],
    [/^AEL syntax error: /gm, "خطای دستور AEL: "],
    [/^No AEL instructions found\.$/gm, "هیچ دستور AEL پیدا نشد."],
    [/^Execution error: /gm, "خطا در اجرا: "],
    [/^Upgrade system is not available\.$/gm, "سامانهٔ ارتقا در دسترس نیست."],
    // conversation fallback and reasoning answers
    [/I don't have enough information to answer that yet\./g, "هنوز اطلاعات کافی برای پاسخ به این پرسش ندارم."],
    [/I have conflicting information about that and can't give a confident answer\./g,
      "دربارهٔ این موضوع اطلاعات متناقض دارم و نمی‌توانم پاسخ مطمئنی بدهم."],
    [/I'd need to reason further than my configured limits allow to answer that\./g,
      "برای پاسخ به این پرسش باید بیش از حد مجاز استدلال کنم."],
    [/Earlier in this conversation you said: /g, "پیش‌تر در همین گفتگو گفتید: "],
    [/I think "([^"]*)" refers to what you said earlier: /g, "فکر می‌کنم «$1» به چیزی اشاره دارد که پیش‌تر گفتید: "],
    [/I'm treating this as a follow-up about "([^"]*)"\. /g, "این را ادامهٔ گفتگو دربارهٔ «$1» در نظر می‌گیرم. "],
    [/What you told me about it: /g, "آنچه دربارهٔ آن به من گفتید: "],
    [/I don't know more about it than what you've told me, so I can't suggest specifics yet\./g,
      "بیش از آنچه به من گفته‌اید دربارهٔ آن نمی‌دانم، پس هنوز نمی‌توانم جزئیات پیشنهاد کنم."],
    [/You can teach me using AEL, for example:/g, "می‌توانید با AEL به من چیزی یاد بدهید، برای مثال:"],
    [/or ask what I already know with: /g, "یا بپرسید چه چیزی می‌دانم: "],
    [/^Here's what I know about '(.*)': /gm, "این چیزی است که دربارهٔ «$1» می‌دانم: "],
    [/^Got it, I'll remember that: /gm, "باشه، به خاطر می‌سپارم: "]
  ];
  // Leading tags of the runtime's structured replies. Only the tag is
  // translated; the value after it goes through REPLY_RULES / stays as-is.
  // The Persian word comes first so the tag resolves right-to-left; the
  // value goes on its own line so an English/Latin value keeps its own
  // direction instead of being interleaved with the Persian tag.
  var TAGS = {
    "[AEL OK]": "[موفق · AEL]",
    "[AEL ERROR]": "[خطا · AEL]",
    "[GOAL CREATED]": "[هدف ایجاد شد]"
  };
  var TAG_RE = /^(\[AEL OK\]|\[AEL ERROR\]|\[GOAL CREATED\]) ?([\s\S]*)$/;

  var EXACT_ERRORS = {
    "internal server error": STR.errorServer,
    "request body too large": STR.errorTooLarge,
    "invalid json": STR.errorBadRequest,
    "invalid Content-Length": STR.errorBadRequest
  };

  var FA_DIGITS = "۰۱۲۳۴۵۶۷۸۹";

  function toPersianDigits(value) {
    return String(value).replace(/[0-9]/g, function (d) { return FA_DIGITS.charAt(+d); });
  }

  // Counts in the info panel: Persian digits for integers, an em dash when missing.
  function formatCount(value) {
    if (value === null || value === undefined || value === "") return "—";
    if (typeof value === "number" && isFinite(value)) return toPersianDigits(value);
    return String(value);
  }

  // "{n}" / "{name}" placeholders in the string table: numbers are written with Persian
  // digits, text (a file name) is isolated left-to-right so Latin names never reorder the sentence.
  // Text that is already Persian (a size such as \u00ab\u06f1\u066b\u06f2 \u06af\u06cc\u06af\u0627\u0628\u0627\u06cc\u062a\u00bb) is passed as plain(text) and put in as it is.
  function plain(text) {
    return { plain: String(text) };
  }

  function fillTemplate(template, values) {
    return String(template).replace(/\{(\w+)\}/g, function (all, key) {
      if (!values || !Object.prototype.hasOwnProperty.call(values, key)) return all;
      var v = values[key];
      if (typeof v === "number" && isFinite(v)) return toPersianDigits(v);
      if (v && typeof v === "object" && typeof v.plain === "string") return v.plain;
      return "\u2066" + String(v) + "\u2069";
    });
  }

  // A size for a person: \u00ab\u06f1\u066b\u06f5 \u06a9\u06cc\u0644\u0648\u0628\u0627\u06cc\u062a\u00bb, \u00ab\u06f4\u066b\u06f0 \u06af\u06cc\u06af\u0627\u0628\u0627\u06cc\u062a\u00bb (Persian digits and decimal separator); under a kilobyte, bytes.
  var SIZE_UNITS = [[1073741824, "\u06af\u06cc\u06af\u0627\u0628\u0627\u06cc\u062a"], [1048576, "\u0645\u06af\u0627\u0628\u0627\u06cc\u062a"], [1024, "\u06a9\u06cc\u0644\u0648\u0628\u0627\u06cc\u062a"]];

  function formatBytes(value) {
    var n = typeof value === "number" && isFinite(value) && value > 0 ? value : 0;
    for (var i = 0; i < SIZE_UNITS.length; i++) {
      if (n >= SIZE_UNITS[i][0]) {
        var v = n / SIZE_UNITS[i][0];
        var shown = v >= 100 ? String(Math.round(v)) : (Math.round(v * 10) / 10).toFixed(1);
        return toPersianDigits(shown.replace(".", "\u066b")) + " " + SIZE_UNITS[i][1];
      }
    }
    return toPersianDigits(Math.round(n)) + " \u0628\u0627\u06cc\u062a";
  }

  // A very long message (a pasted extension package, say) is SHOWN shortened in its bubble; the
  // text that is sent to the runtime is never shortened. Counts code points, so no character is cut in half.
  function shortenForDisplay(text, limit) {
    if (typeof text !== "string") return "";
    var max = typeof limit === "number" && limit >= 1 ? Math.floor(limit) : 600;
    var chars = Array.from(text);
    if (chars.length <= max) return text;
    return chars.slice(0, max).join("") + "\n" + fillTemplate(STR.longMessage, { n: chars.length });
  }

  // The assistant folds every run of whitespace in a message into ONE space before anything reads it. A package
  // carries Python code whose meaning depends on indentation, so just before a message that holds a package is
  // SENT it is rewritten so that no whitespace is left to fold:
  //   * a JSON package ("schema": "ext.v1" | "code.v1" | "lang.v1"): that object is rewritten compactly with every
  //     space of a run (and every exotic space character) written as a \uXXXX escape. The JSON means exactly the same.
  //   * a package in its text form (a line "=== PACK code.v1 ===" ... "=== END PACK ==="): the whole message becomes
  //     ONE line, "=== ESCAPED TEXT v1 === <body>", whose newlines, tabs and runs of spaces are written as escapes.
  //     The assistant's Persian brain decodes it first thing (persian_brain/wire_text.py; a test runs both coders on
  //     the same texts and demands the same result).
  // Anything that is not such a package is returned untouched.
  var PACKAGE_MARKS = ["ext.v1", "code.v1", "lang.v1"];
  var MAX_OBJECT_TRIES = 6;
  var EXOTIC_SPACE = /[\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]/g;
  var PACK_HEADER_LINE = /^[ \t]*=== PACK (?:code|lang)\.v[0-9]{1,4} ===[ \t]*$/m;
  var WIRE_MARK = "=== ESCAPED TEXT v1 ===";
  // every character the core's folding treats as white space, except the plain space (its runs have their own rule)
  var WIRE_WHITE = /[\t\n\u000b\u000c\r\u001c-\u001f\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]/g;

  function objectEnd(text, start) {
    var depth = 0;
    var inString = false;
    for (var i = start; i < text.length; i++) {
      var c = text.charAt(i);
      if (inString) {
        if (c === "\\") i++;
        else if (c === '"') inString = false;
      } else if (c === '"') {
        inString = true;
      } else if (c === "{") {
        depth++;
      } else if (c === "}") {
        depth--;
        if (depth === 0) return i;
      }
    }
    return -1;
  }

  function escapeSpaces(json) {
    return json
      .replace(/ {2,}/g, function (run) {
        var out = " ";
        for (var i = 1; i < run.length; i++) out += "\\u0020";
        return out;
      })
      .replace(EXOTIC_SPACE, function (ch) {
        return "\\u" + ("0000" + ch.charCodeAt(0).toString(16)).slice(-4);
      });
  }

  function mentionsPackageMark(text) {
    for (var i = 0; i < PACKAGE_MARKS.length; i++) {
      if (text.indexOf(PACKAGE_MARKS[i]) !== -1) return true;
    }
    return false;
  }

  function protectJsonPackage(text) {
    if (!mentionsPackageMark(text)) return text;
    var start = text.indexOf("{");
    for (var tries = 0; start !== -1 && tries < MAX_OBJECT_TRIES; tries++) {
      var end = objectEnd(text, start);
      if (end !== -1) {
        var obj = null;                       // the slice starts with "{": JSON.parse gives an object or throws
        try { obj = JSON.parse(text.slice(start, end + 1)); } catch (e) { obj = null; }
        if (obj && PACKAGE_MARKS.indexOf(obj.schema) !== -1) {
          return text.slice(0, start) + escapeSpaces(JSON.stringify(obj)) + text.slice(end + 1);
        }
      }
      start = text.indexOf("{", start + 1);
    }
    return text;
  }

  function wireWhite(ch) {
    if (ch === "\n") return "\\n";
    if (ch === "\t") return "\\t";
    if (ch === "\r") return "\\r";
    return "\\u" + ("0000" + ch.charCodeAt(0).toString(16)).slice(-4);
  }

  // One space between two other characters stays; every space that touches another space, or an end, is "\s".
  function wireSpaces(run, at, whole) {
    if (run.length === 1 && at > 0 && at + 1 < whole.length) return run;
    var out = "";
    for (var i = 0; i < run.length; i++) out += "\\s";
    return out;
  }

  function encodeWire(text) {
    var body = text.replace(/\\/g, "\\\\").replace(WIRE_WHITE, wireWhite).replace(/ +/g, wireSpaces);
    return body === "" ? WIRE_MARK : WIRE_MARK + " " + body;
  }

  // The text form wins: a header line makes the whole message one package, and a JSON-looking piece inside its source
  // code is just source (rewriting it would change the code).
  function protectPackage(text) {
    if (typeof text !== "string") return text;
    if (PACK_HEADER_LINE.test(text)) return encodeWire(text);
    return protectJsonPackage(text);
  }

  function statusLabel(value) {
    var key = String(value === null || value === undefined ? "" : value).toLowerCase();
    return Object.prototype.hasOwnProperty.call(STATUS, key) ? STATUS[key] : String(value);
  }

  function localizeLine(line) {
    var tag = "";
    var m = TAG_RE.exec(line);
    if (m) {
      tag = TAGS[m[1]] + (m[2] === "" ? "" : "\n");
      line = m[2];
    }
    for (var i = 0; i < REPLY_RULES.length; i++) line = line.replace(REPLY_RULES[i][0], REPLY_RULES[i][1]);
    return tag + line;
  }

  // Line by line, so every structured line keeps its own tag and no rule
  // can ever span (and corrupt) two lines.
  function localizeReply(text) {
    if (typeof text !== "string" || text === "") return STR.emptyReply;
    return text.split("\n").map(localizeLine).join("\n");
  }

  function localizeError(message, httpStatus) {
    if (typeof message === "string" && Object.prototype.hasOwnProperty.call(EXACT_ERRORS, message)) {
      return EXACT_ERRORS[message];
    }
    if (httpStatus === 413) return STR.errorTooLarge;
    if (httpStatus >= 400 && httpStatus < 500) return STR.errorBadRequest;
    return STR.errorServer;
  }

  var api = {
    STR: STR,
    STATUS: STATUS,
    toPersianDigits: toPersianDigits,
    formatCount: formatCount,
    fillTemplate: fillTemplate,
    plain: plain,
    formatBytes: formatBytes,
    shortenForDisplay: shortenForDisplay,
    protectPackage: protectPackage,
    encodeWire: encodeWire,
    statusLabel: statusLabel,
    localizeReply: localizeReply,
    localizeError: localizeError
  };

  root.FaUI = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof window !== "undefined" ? window : globalThis);
