package com.erfan.standaloneai;

import android.os.Bundle;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Toast;

import androidx.appcompat.app.AppCompatActivity;

import com.chaquo.python.PyObject;
import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;

public class MainActivity extends AppCompatActivity {

    private WebView webView;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);

        webView = findViewById(R.id.webview);
        webView.getSettings().setJavaScriptEnabled(true);
        webView.getSettings().setDomStorageEnabled(true);
        webView.setWebViewClient(new WebViewClient());

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
            Toast.makeText(this, "Startup error: " + e.getMessage(), Toast.LENGTH_LONG).show();
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
