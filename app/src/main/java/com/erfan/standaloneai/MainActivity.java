package com.erfan.standaloneai;

import android.content.ActivityNotFoundException;
import android.content.ContentResolver;
import android.content.Intent;
import android.database.Cursor;
import android.graphics.Bitmap;
import android.graphics.Color;
import android.net.Uri;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.StatFs;
import android.provider.OpenableColumns;
import android.speech.RecognizerIntent;
import android.webkit.JavascriptInterface;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Toast;

import androidx.appcompat.app.AppCompatActivity;
import androidx.core.app.ActivityCompat;

import com.chaquo.python.PyObject;
import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.util.ArrayList;
import java.util.Locale;
import java.util.concurrent.Callable;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;

public class MainActivity extends AppCompatActivity {

    /**
     * Prompt 957: the native features THIS APK really contains. The Python layer
     * (android_adapters, native_bridge) reads this list to tell an old APK from a new one;
     * an APK built before this field existed simply has no native features.
     * Add a name here only together with the code that implements it.
     *
     * Prompt 958: voice_input (the system's speech dialog), accessibility (PyAccessibilityService),
     * share_target (text shared INTO this app), file_pick (the document picker that copies the
     * chosen file into the app's inbox without loading it into memory).
     */
    public static final String[] NATIVE_FEATURES = {
            "file_chooser", "permission_request", "voice_input", "accessibility", "share_target", "file_pick"};

    private static final int REQUEST_FILE_CHOOSER = 9571;
    private static final int REQUEST_PERMISSIONS = 9572;
    private static final int REQUEST_VOICE = 9573;
    private static final int REQUEST_PICK_FILE = 9574;

    private static final String PURPOSE_MODEL = "model";
    private static final String PURPOSE_FILE = "file";
    private static final long MAX_MODEL_BYTES = 8L * 1024L * 1024L * 1024L;     // the same ceiling as the model store
    private static final long MAX_OTHER_BYTES = 64L * 1024L * 1024L;
    private static final long MIN_FREE_BYTES = 100L * 1024L * 1024L;            // left free after the copy
    private static final int MAX_NAME_CHARS = 100;                              // the inbox accepts names of at most 100 characters
    private static final long PROGRESS_EVERY_NANOS = 700000000L;
    private static final int RETRY_LIMIT = 20;
    private static final int QUEUE_LIMIT = 20;

    // The one live activity, so Python can ask for a permission dialog or the speech dialog (null when none is open).
    private static MainActivity instance;
    // The last speech result that nobody on the page asked for (Python picks it up with takeVoiceResult()).
    private static volatile String voiceResult = "";

    private WebView webView;
    private ValueCallback<Uri[]> filePathCallback;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private final ArrayList<String[]> queued = new ArrayList<String[]>();        // events for the page, kept until it is ready
    private final AtomicBoolean copying = new AtomicBoolean(false);

    private String filesDirPath = "";
    private String inboxPath = "";
    private String originScheme = "";
    private String originHost = "";
    private int originPort = -1;
    private String pickPurpose = PURPOSE_FILE;
    private boolean voiceForPage = false;
    private volatile boolean started = false;
    private volatile boolean pageTrusted = false;
    private volatile boolean pageReady = false;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);
        filesDirPath = getFilesDir().getAbsolutePath();
        inboxPath = new File(new File(new File(getFilesDir(), "data"), "brain_hub"), "inbox").getAbsolutePath();

        webView = findViewById(R.id.webview);
        webView.getSettings().setJavaScriptEnabled(true);
        webView.getSettings().setDomStorageEnabled(true);
        webView.setWebViewClient(new LocalOnlyClient());
        // Prompt 957: lets the page's <input type="file"> open Android's document picker.
        // Only the files the user picks are handed to the page; no storage permission is needed.
        webView.setWebChromeClient(new WebChromeClient() {
            @Override
            public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> callback,
                                             WebChromeClient.FileChooserParams params) {
                if (filePathCallback != null) {
                    filePathCallback.onReceiveValue(null);
                }
                filePathCallback = callback;
                try {
                    startActivityForResult(params.createIntent(), REQUEST_FILE_CHOOSER);
                } catch (ActivityNotFoundException e) {
                    filePathCallback = null;
                    Toast.makeText(MainActivity.this, getString(R.string.file_chooser_unavailable), Toast.LENGTH_SHORT).show();
                    return false;
                }
                return true;
            }
        });
        // Prompt 958: the page's own buttons (file dialog, voice). Only the local page may use them (see LocalOnlyClient).
        webView.addJavascriptInterface(new NativeBridge(), "AndroidBridge");
        // Match the dark page so nothing flashes white while it loads.
        webView.setBackgroundColor(Color.parseColor("#0A0B0F"));
        instance = this;

        if (!Python.isStarted()) {
            Python.start(new AndroidPlatform(this));
        }

        try {
            Python py = Python.getInstance();
            runBootStep(py);
            PyObject androidEntry = py.getModule("android_entry");
            PyObject urlObj = androidEntry.callAttr("start", filesDirPath);
            String url = urlObj.toString();
            rememberOrigin(url);
            webView.loadUrl(url);
        } catch (Exception e) {
            Toast.makeText(this, getString(R.string.startup_error, e.getMessage()), Toast.LENGTH_LONG).show();
        }

        if (savedInstanceState == null) {
            handleIntent(getIntent());
        }
    }

    /**
     * Prompt 958: the first Python call. It lets the pack system make the active packs importable BEFORE the app
     * is imported, and tells us where the inbox is. It can never keep the app from starting: any failure is ignored
     * and the inbox path computed above (the same folder) is used.
     */
    private void runBootStep(Python py) {
        try {
            PyObject boot = py.getModule("platform_boot");
            boot.callAttr("prepare", filesDirPath);
            String path = boot.callAttr("inbox_dir", filesDirPath).toString();
            if (path != null && !path.isEmpty()) {
                inboxPath = path;
            }
        } catch (RuntimeException e) {
            // The app starts without the pack system's boot step.
        }
    }

    // ------------------------------------------------------------------------------------------ life cycle
    @Override
    protected void onStart() {
        super.onStart();
        started = true;
    }

    @Override
    protected void onStop() {
        started = false;
        super.onStop();
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        handleIntent(intent);
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        if (requestCode == REQUEST_FILE_CHOOSER) {
            if (filePathCallback != null) {
                // A cancelled picker yields null, which tells the page that nothing was chosen.
                filePathCallback.onReceiveValue(WebChromeClient.FileChooserParams.parseResult(resultCode, data));
                filePathCallback = null;
            }
            return;
        }
        if (requestCode == REQUEST_PICK_FILE) {
            if (resultCode == RESULT_OK && data != null && data.getData() != null) {
                startCopy(data.getData(), pickPurpose);
            } else {
                tellPage("nativeOnFile", fileResult(false, "cancelled", "", 0L, pickPurpose), true);
            }
            return;
        }
        if (requestCode == REQUEST_VOICE) {
            String text = "";
            if (resultCode == RESULT_OK && data != null) {
                ArrayList<String> results = data.getStringArrayListExtra(RecognizerIntent.EXTRA_RESULTS);
                if (results != null && !results.isEmpty() && results.get(0) != null) {
                    text = results.get(0);
                }
            }
            if (voiceForPage) {
                voiceForPage = false;
                tellPage("nativeOnVoice", voiceJson(text), true);
            } else {
                voiceResult = text;
            }
            return;
        }
        super.onActivityResult(requestCode, resultCode, data);
    }

    @Override
    protected void onDestroy() {
        if (filePathCallback != null) {
            filePathCallback.onReceiveValue(null);
            filePathCallback = null;
        }
        handler.removeCallbacksAndMessages(null);
        if (instance == this) {
            instance = null;
        }
        super.onDestroy();
    }

    // ------------------------------------------------------------------------------------------ permissions (Prompt 957)
    /**
     * Prompt 957: asks Android to show its permission dialog (on the UI thread) and returns
     * whether the request was DISPATCHED. It never reports the user's decision: Python
     * observes that later by re-checking the permission. Called from android_adapters.
     */
    public static boolean requestAndroidPermissions(final String[] permissions) {
        final MainActivity activity = instance;
        if (activity == null || permissions == null || permissions.length == 0) {
            return false;
        }
        activity.runOnUiThread(new Runnable() {
            @Override
            public void run() {
                ActivityCompat.requestPermissions(activity, permissions, REQUEST_PERMISSIONS);
            }
        });
        return true;
    }

    // ------------------------------------------------------------------------------------------ voice input (Prompt 958)
    /**
     * Opens the system's speech dialog (language such as "fa-IR") and returns whether it was really started.
     * The text arrives later: Python picks it up with takeVoiceResult(). False when this screen is not in front.
     */
    public static boolean startVoiceInput(final String lang) {
        MainActivity activity = instance;
        if (activity == null) {
            return false;
        }
        return activity.dispatchVoice(lang, false);
    }

    /** The last speech result that was asked for from Python, once ("" when there is none). */
    public static String takeVoiceResult() {
        String value = voiceResult;
        voiceResult = "";
        return value == null ? "" : value;
    }

    private boolean dispatchVoice(final String lang, final boolean forPage) {
        return onUiThreadAndWait(new Callable<Boolean>() {
            @Override
            public Boolean call() {
                if (!started) {
                    return Boolean.FALSE;                       // the speech dialog can only open over a visible screen
                }
                try {
                    Intent intent = new Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH);
                    intent.putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM);
                    intent.putExtra(RecognizerIntent.EXTRA_LANGUAGE, cleanLanguage(lang));
                    intent.putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 1);
                    intent.putExtra(RecognizerIntent.EXTRA_PROMPT, getString(R.string.voice_prompt));
                    voiceForPage = forPage;
                    voiceResult = "";
                    startActivityForResult(intent, REQUEST_VOICE);
                    return Boolean.TRUE;
                } catch (ActivityNotFoundException e) {
                    Toast.makeText(MainActivity.this, getString(R.string.voice_unavailable), Toast.LENGTH_LONG).show();
                    return Boolean.FALSE;
                } catch (RuntimeException e) {
                    return Boolean.FALSE;
                }
            }
        });
    }

    private static String cleanLanguage(String lang) {
        if (lang == null || lang.length() < 2 || lang.length() > 20) {
            return "fa-IR";
        }
        for (int i = 0; i < lang.length(); i++) {
            char c = lang.charAt(i);
            boolean ok = (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == '-';
            if (!ok) {
                return "fa-IR";
            }
        }
        return lang;
    }

    private static String voiceJson(String text) {
        try {
            JSONObject o = new JSONObject();
            o.put("ok", text != null && !text.trim().isEmpty());
            o.put("text", text == null ? "" : text);
            return o.toString();
        } catch (JSONException e) {
            return "{\"ok\":false,\"text\":\"\"}";
        }
    }

    // ------------------------------------------------------------------------------------------ text shared INTO the app
    /** A text another app shared into this one (the user chose this app in its Share sheet). Nothing is run or sent. */
    private void handleIntent(Intent intent) {
        if (intent == null || !Intent.ACTION_SEND.equals(intent.getAction())) {
            return;
        }
        if ((intent.getFlags() & Intent.FLAG_ACTIVITY_LAUNCHED_FROM_HISTORY) != 0) {
            return;                                             // the same share must not be taken again when the app is reopened from Recents
        }
        String type = intent.getType();
        CharSequence text = intent.getCharSequenceExtra(Intent.EXTRA_TEXT);
        intent.setAction(Intent.ACTION_MAIN);                   // consumed
        intent.removeExtra(Intent.EXTRA_TEXT);
        if (type == null || !type.startsWith("text/") || text == null || text.toString().trim().isEmpty()) {
            return;
        }
        deliverSharedText(text.toString());
    }

    private void deliverSharedText(final String text) {
        final String dir = filesDirPath;
        Thread worker = new Thread(new Runnable() {
            @Override
            public void run() {
                String answer = "{\"ok\":false,\"code\":\"error\"}";
                try {
                    PyObject boot = Python.getInstance().getModule("platform_boot");
                    answer = boot.callAttr("on_shared_text", dir, text).toString();
                } catch (RuntimeException e) {
                    // the page is told that it failed
                }
                tellPage("nativeOnShared", answer, true);
            }
        }, "shared-text");
        worker.start();
    }

    // ------------------------------------------------------------------------------------------ the page's buttons
    /**
     * Prompt 958: what the page may ask of the phone. It is exposed only to the app's own local page
     * (every method checks that), and each action needs the user's own tap in an Android dialog.
     */
    public final class NativeBridge {

        @JavascriptInterface
        public String features() {
            JSONArray list = new JSONArray();
            for (String name : NATIVE_FEATURES) {
                list.put(name);
            }
            return list.toString();
        }

        /** Opens Android's document picker; the chosen file is copied into the inbox. purpose: "model" or "file". */
        @JavascriptInterface
        public boolean pickFile(String purpose) {
            if (!pageTrusted) {
                return false;
            }
            final String wanted = PURPOSE_MODEL.equals(purpose) ? PURPOSE_MODEL : PURPOSE_FILE;
            return onUiThreadAndWait(new Callable<Boolean>() {
                @Override
                public Boolean call() {
                    if (!started) {
                        return Boolean.FALSE;
                    }
                    try {
                        Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT);
                        intent.addCategory(Intent.CATEGORY_OPENABLE);
                        intent.setType("*/*");
                        pickPurpose = wanted;
                        startActivityForResult(intent, REQUEST_PICK_FILE);
                        return Boolean.TRUE;
                    } catch (ActivityNotFoundException e) {
                        Toast.makeText(MainActivity.this, getString(R.string.file_chooser_unavailable), Toast.LENGTH_SHORT).show();
                        return Boolean.FALSE;
                    } catch (RuntimeException e) {
                        return Boolean.FALSE;
                    }
                }
            });
        }

        /** Opens the system's speech dialog; the recognised text comes back to the page (window.nativeOnVoice). */
        @JavascriptInterface
        public boolean startVoice(String lang) {
            if (!pageTrusted) {
                return false;
            }
            return dispatchVoice(lang, true);
        }
    }

    // ------------------------------------------------------------------------------------------ copying a picked file
    private void startCopy(final Uri uri, final String purpose) {
        if (!copying.compareAndSet(false, true)) {
            tellPage("nativeOnFile", fileResult(false, "busy", "", 0L, purpose), true);
            return;
        }
        Thread worker = new Thread(new Runnable() {
            @Override
            public void run() {
                String answer;
                try {
                    answer = copyPickedFile(uri, purpose);
                } catch (RuntimeException e) {
                    answer = fileResult(false, "error", "", 0L, purpose);
                } finally {
                    copying.set(false);
                }
                tellPage("nativeOnFile", answer, true);
            }
        }, "file-copy");
        worker.start();
    }

    /**
     * Copies the picked document into the inbox in 1 MB pieces (a model can be several gigabytes: it is never
     * held in memory and never goes through the page). The file is written under a ".partial" name and renamed
     * only when the whole thing is there and its size matches what Android reported.
     */
    private String copyPickedFile(Uri uri, String purpose) {
        ContentResolver resolver = getContentResolver();
        String name = safeFileName(queryDisplayName(resolver, uri));
        long expected = querySize(resolver, uri);
        long ceiling = PURPOSE_MODEL.equals(purpose) ? MAX_MODEL_BYTES : MAX_OTHER_BYTES;
        if (PURPOSE_MODEL.equals(purpose) && !hasModelExtension(name)) {
            return fileResult(false, "unsupported_type", name, 0L, purpose);
        }
        if (expected > ceiling) {
            return fileResult(false, "too_large", name, expected, purpose);
        }
        File dir = new File(inboxPath);
        if (!dir.isDirectory() && !dir.mkdirs() && !dir.isDirectory()) {
            return fileResult(false, "no_inbox", name, 0L, purpose);
        }
        try {
            long free = new StatFs(dir.getAbsolutePath()).getAvailableBytes();
            if (free < Math.max(expected, 0L) + MIN_FREE_BYTES) {
                return fileResult(false, "no_space", name, expected, purpose);
            }
        } catch (RuntimeException e) {
            // free space unknown: the copy itself fails cleanly when the disk is full
        }
        File target = new File(dir, name);
        File partial = new File(dir, name + ".partial");
        long copied = 0L;
        boolean complete = false;
        InputStream in = null;
        FileOutputStream out = null;
        try {
            in = resolver.openInputStream(uri);
            if (in == null) {
                return fileResult(false, "unreadable", name, 0L, purpose);
            }
            out = new FileOutputStream(partial);
            byte[] buffer = new byte[1024 * 1024];
            long lastReport = System.nanoTime();
            int n;
            while ((n = in.read(buffer)) != -1) {
                out.write(buffer, 0, n);
                copied += n;
                if (copied > ceiling) {
                    return fileResult(false, "too_large", name, copied, purpose);
                }
                long now = System.nanoTime();
                if (now - lastReport >= PROGRESS_EVERY_NANOS) {
                    lastReport = now;
                    tellPage("nativeOnProgress", progressJson(name, copied, expected), false);
                }
            }
            out.flush();
            out.getFD().sync();
            complete = true;
        } catch (IOException e) {
            return fileResult(false, "io_error", name, copied, purpose);
        } catch (SecurityException e) {
            return fileResult(false, "unreadable", name, copied, purpose);
        } finally {
            closeQuietly(in);
            closeQuietly(out);
            if (!complete) {
                partial.delete();
            }
        }
        if (copied == 0L) {
            partial.delete();
            return fileResult(false, "empty", name, 0L, purpose);
        }
        if (expected > 0L && copied != expected) {
            partial.delete();
            return fileResult(false, "size_mismatch", name, copied, purpose);
        }
        if (!partial.renameTo(target)) {
            partial.delete();
            return fileResult(false, "io_error", name, copied, purpose);
        }
        return fileResult(true, "copied", name, copied, purpose);
    }

    private static boolean hasModelExtension(String name) {
        String lower = name.toLowerCase(Locale.ROOT);
        return lower.endsWith(".task") || lower.endsWith(".gguf");
    }

    private static void closeQuietly(java.io.Closeable closeable) {
        if (closeable == null) {
            return;
        }
        try {
            closeable.close();
        } catch (IOException e) {
            // nothing more to do
        }
    }

    private static String queryDisplayName(ContentResolver resolver, Uri uri) {
        Cursor cursor = null;
        try {
            cursor = resolver.query(uri, new String[] {OpenableColumns.DISPLAY_NAME}, null, null, null);
            if (cursor != null && cursor.moveToFirst() && !cursor.isNull(0)) {
                return cursor.getString(0);
            }
        } catch (RuntimeException e) {
            // fall back to the last path segment below
        } finally {
            if (cursor != null) {
                cursor.close();
            }
        }
        String last = uri.getLastPathSegment();
        return last == null ? "" : last;
    }

    private static long querySize(ContentResolver resolver, Uri uri) {
        Cursor cursor = null;
        try {
            cursor = resolver.query(uri, new String[] {OpenableColumns.SIZE}, null, null, null);
            if (cursor != null && cursor.moveToFirst() && !cursor.isNull(0)) {
                return cursor.getLong(0);
            }
        } catch (RuntimeException e) {
            // size unknown
        } finally {
            if (cursor != null) {
                cursor.close();
            }
        }
        return -1L;
    }

    /**
     * A file name the app's inbox accepts: letters, digits, dot, dash and underscore only, a letter or digit first,
     * at most 100 characters, the extension kept (in lower case). Anything else becomes an underscore.
     */
    static String safeFileName(String display) {
        String base = display == null ? "" : display.trim();
        int slash = Math.max(base.lastIndexOf('/'), base.lastIndexOf('\\'));
        if (slash >= 0) {
            base = base.substring(slash + 1);
        }
        int dot = base.lastIndexOf('.');
        String stem = dot > 0 ? base.substring(0, dot) : (dot == 0 ? "" : base);
        String ext = dot >= 0 ? base.substring(dot + 1) : "";
        stem = cleanPart(stem);
        ext = cleanPart(ext).toLowerCase(Locale.ROOT);
        if (stem.isEmpty()) {
            stem = "file";
        }
        if (ext.length() > 12) {
            ext = ext.substring(0, 12);
        }
        int room = MAX_NAME_CHARS - (ext.isEmpty() ? 0 : ext.length() + 1);
        if (stem.length() > room) {
            stem = stem.substring(0, room);
        }
        return ext.isEmpty() ? stem : stem + "." + ext;
    }

    private static String cleanPart(String part) {
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < part.length(); i++) {
            char c = part.charAt(i);
            boolean ok = (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == '.' || c == '-' || c == '_';
            boolean underscore = !ok;
            char put = ok ? c : '_';
            if (underscore && sb.length() > 0 && sb.charAt(sb.length() - 1) == '_') {
                continue;                                       // one underscore for a run of odd characters
            }
            sb.append(put);
        }
        int start = 0;
        while (start < sb.length() && !isAsciiLetterOrDigit(sb.charAt(start))) {
            start++;
        }
        int end = sb.length();
        while (end > start && sb.charAt(end - 1) == '_') {
            end--;
        }
        return sb.substring(start, end);
    }

    private static boolean isAsciiLetterOrDigit(char c) {
        return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9');
    }

    private static String fileResult(boolean ok, String code, String name, long size, String purpose) {
        try {
            JSONObject o = new JSONObject();
            o.put("ok", ok);
            o.put("code", code);
            o.put("name", name == null ? "" : name);
            o.put("size", size);
            o.put("purpose", purpose);
            return o.toString();
        } catch (JSONException e) {
            return "{\"ok\":false,\"code\":\"error\"}";
        }
    }

    private static String progressJson(String name, long copied, long total) {
        try {
            JSONObject o = new JSONObject();
            o.put("name", name);
            o.put("copied", copied);
            o.put("total", Math.max(total, 0L));
            return o.toString();
        } catch (JSONException e) {
            return "{}";
        }
    }

    // ------------------------------------------------------------------------------------------ talking to the page
    /**
     * Calls window.<callback>(<json text>) in the page. Until the page has finished loading the event waits
     * (at most 20 of them); {@code retry} says whether to try again for a while when the page has not defined
     * the function yet. The callback names are fixed in this file - nothing from outside is ever run.
     */
    private void tellPage(final String callback, final String json, final boolean retry) {
        runOnUiThread(new Runnable() {
            @Override
            public void run() {
                if (webView == null || isFinishing()) {
                    return;
                }
                if (!pageReady) {
                    if (retry && queued.size() < QUEUE_LIMIT) {
                        queued.add(new String[] {callback, json});
                    }
                    return;
                }
                callPage(callback, json, 0, retry);
            }
        });
    }

    private void callPage(final String callback, final String json, final int attempt, final boolean retry) {
        String script = "(function(){var f=window." + callback + ";if(typeof f==='function'){f("
                + JSONObject.quote(json) + ");return true;}return false;})()";
        webView.evaluateJavascript(script, new ValueCallback<String>() {
            @Override
            public void onReceiveValue(String value) {
                if (!"true".equals(value) && retry && attempt < RETRY_LIMIT) {
                    handler.postDelayed(new Runnable() {
                        @Override
                        public void run() {
                            if (webView != null && !isFinishing() && pageReady) {
                                callPage(callback, json, attempt + 1, retry);
                            }
                        }
                    }, 500L);
                }
            }
        });
    }

    private void flushQueued() {
        ArrayList<String[]> events = new ArrayList<String[]>(queued);
        queued.clear();
        for (String[] event : events) {
            callPage(event[0], event[1], 0, true);
        }
    }

    /** Runs {@code job} on the UI thread and returns its answer (false after 3 seconds). Safe to call from any thread. */
    private boolean onUiThreadAndWait(final Callable<Boolean> job) {
        if (Looper.myLooper() == Looper.getMainLooper()) {
            try {
                return Boolean.TRUE.equals(job.call());
            } catch (Exception e) {
                return false;
            }
        }
        final AtomicBoolean result = new AtomicBoolean(false);
        final CountDownLatch done = new CountDownLatch(1);
        runOnUiThread(new Runnable() {
            @Override
            public void run() {
                try {
                    result.set(Boolean.TRUE.equals(job.call()));
                } catch (Exception e) {
                    result.set(false);
                } finally {
                    done.countDown();
                }
            }
        });
        try {
            if (!done.await(3L, TimeUnit.SECONDS)) {
                return false;
            }
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            return false;
        }
        return result.get();
    }

    // ------------------------------------------------------------------------------------------ the page itself
    private void rememberOrigin(String url) {
        Uri uri = Uri.parse(url);
        originScheme = uri.getScheme() == null ? "" : uri.getScheme();
        originHost = uri.getHost() == null ? "" : uri.getHost();
        originPort = uri.getPort();
    }

    /** Is this the app's own local page (the address the Python side returned from start())? */
    private boolean isLocalPage(Uri uri) {
        return uri != null && !originHost.isEmpty()
                && originScheme.equals(uri.getScheme())
                && originHost.equals(uri.getHost())
                && originPort == uri.getPort();
    }

    /**
     * The page may load only the app's own local address. A link to anywhere else never loads inside this
     * WebView (which has the page's buttons); a secure link is handed to the phone's browser, anything else is dropped.
     */
    private final class LocalOnlyClient extends WebViewClient {
        @Override
        public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
            Uri uri = request.getUrl();
            if (isLocalPage(uri)) {
                return false;
            }
            if (uri != null && "https".equals(uri.getScheme())) {
                try {
                    startActivity(new Intent(Intent.ACTION_VIEW, uri));
                } catch (ActivityNotFoundException e) {
                    // no browser: nothing to open
                }
            }
            return true;
        }

        @Override
        public void onPageStarted(WebView view, String url, Bitmap favicon) {
            pageReady = false;
            pageTrusted = isLocalPage(Uri.parse(url));
        }

        @Override
        public void onPageFinished(WebView view, String url) {
            pageTrusted = isLocalPage(Uri.parse(url));
            if (pageTrusted) {
                pageReady = true;
                flushQueued();
            }
        }
    }

    @Override
    public void onBackPressed() {
        if (webView.canGoBack()) {
            webView.goBack();
        } else {
            super.onBackPressed();
        }
    }
}
