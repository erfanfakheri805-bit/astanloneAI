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
  function fillTemplate(template, values) {
    return String(template).replace(/\{(\w+)\}/g, function (all, key) {
      if (!values || !Object.prototype.hasOwnProperty.call(values, key)) return all;
      var v = values[key];
      if (typeof v === "number" && isFinite(v)) return toPersianDigits(v);
      return "\u2066" + String(v) + "\u2069";
    });
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

  // The assistant folds every run of whitespace in a message into ONE space before anything reads it. An
  // extension package carries Python code whose meaning depends on indentation, so just before a message that
  // holds a package ("schema": "ext.v1") is SENT, that JSON object is rewritten compactly with every space of a
  // run (and every exotic space character) written as a \uXXXX escape. The JSON means exactly the same; no
  // whitespace is left to fold. Anything that is not such a package is returned untouched.
  var PACKAGE_MARK = "ext.v1";
  var MAX_OBJECT_TRIES = 6;
  var EXOTIC_SPACE = /[\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]/g;

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

  function protectPackage(text) {
    if (typeof text !== "string" || text.indexOf(PACKAGE_MARK) === -1) return text;
    var start = text.indexOf("{");
    for (var tries = 0; start !== -1 && tries < MAX_OBJECT_TRIES; tries++) {
      var end = objectEnd(text, start);
      if (end !== -1) {
        var obj = null;                       // the slice starts with "{": JSON.parse gives an object or throws
        try { obj = JSON.parse(text.slice(start, end + 1)); } catch (e) { obj = null; }
        if (obj && obj.schema === PACKAGE_MARK) {
          return text.slice(0, start) + escapeSpaces(JSON.stringify(obj)) + text.slice(end + 1);
        }
      }
      start = text.indexOf("{", start + 1);
    }
    return text;
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
    shortenForDisplay: shortenForDisplay,
    protectPackage: protectPackage,
    statusLabel: statusLabel,
    localizeReply: localizeReply,
    localizeError: localizeError
  };

  root.FaUI = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof window !== "undefined" ? window : globalThis);
