package com.erfan.standaloneai;

import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.graphics.Color;
import android.net.Uri;
import android.os.Bundle;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Toast;

import androidx.appcompat.app.AppCompatActivity;
import androidx.core.app.ActivityCompat;

import com.chaquo.python.PyObject;
import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;

public class MainActivity extends AppCompatActivity {

    /**
     * Prompt 957: the native features THIS APK really contains. The Python layer
     * (android_adapters) reads this list to tell an old APK from a new one; an
     * APK built before this field existed simply has no native features.
     * Add a name here only together with the code that implements it.
     */
    public static final String[] NATIVE_FEATURES = {"file_chooser", "permission_request"};

    private static final int REQUEST_FILE_CHOOSER = 9571;
    private static final int REQUEST_PERMISSIONS = 9572;

    // The one live activity, so Python can ask for a permission dialog (null when none is open).
    private static MainActivity instance;

    private WebView webView;
    private ValueCallback<Uri[]> filePathCallback;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);

        webView = findViewById(R.id.webview);
        webView.getSettings().setJavaScriptEnabled(true);
        webView.getSettings().setDomStorageEnabled(true);
        webView.setWebViewClient(new WebViewClient());
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
        // Match the dark page so nothing flashes white while it loads.
        webView.setBackgroundColor(Color.parseColor("#0A0B0F"));
        instance = this;

        if (!Python.isStarted()) {
            Python.start(new AndroidPlatform(this));
        }

        try {
            Python py = Python.getInstance();
            PyObject androidEntry = py.getModule("android_entry");
            String filesDir = getFilesDir().getAbsolutePath();
            PyObject urlObj = androidEntry.callAttr("start", filesDir);
            String url = urlObj.toString();
            webView.loadUrl(url);
        } catch (Exception e) {
            Toast.makeText(this, getString(R.string.startup_error, e.getMessage()), Toast.LENGTH_LONG).show();
        }
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
        super.onActivityResult(requestCode, resultCode, data);
    }

    @Override
    protected void onDestroy() {
        if (filePathCallback != null) {
            filePathCallback.onReceiveValue(null);
            filePathCallback = null;
        }
        if (instance == this) {
            instance = null;
        }
        super.onDestroy();
    }

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

    @Override
    public void onBackPressed() {
        if (webView.canGoBack()) {
            webView.goBack();
        } else {
            super.onBackPressed();
        }
    }
}
