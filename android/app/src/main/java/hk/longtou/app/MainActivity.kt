package hk.longtou.app

import android.annotation.SuppressLint
import android.app.Activity
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.VibrationEffect
import android.os.Vibrator
import android.webkit.JavascriptInterface
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient

/** 外殼：全畫面 WebView 載入 GitHub Pages 上面嘅 app。持倉資料存喺 WebView 嘅 localStorage。 */
class MainActivity : Activity() {
    private lateinit var web: WebView

    /** 網頁嘅 buzz() 經呢度震（window.AndroidHaptics）。淨係得呢一個方法，網頁攞唔到手機其他嘢；外部網址唔會喺呢個 WebView 開。 */
    @Suppress("DEPRECATION")
    inner class Haptics {
        private val vibrator = getSystemService(Context.VIBRATOR_SERVICE) as? Vibrator

        @JavascriptInterface
        fun buzz(kind: String) {
            val v = vibrator ?: return
            if (Build.VERSION.SDK_INT >= 29) {   // 系統預設效果：每部手機都調校過，短而清晰
                v.vibrate(VibrationEffect.createPredefined(when (kind) {
                    "tick" -> VibrationEffect.EFFECT_TICK
                    "light" -> VibrationEffect.EFFECT_CLICK
                    "medium" -> VibrationEffect.EFFECT_HEAVY_CLICK
                    "success" -> VibrationEffect.EFFECT_DOUBLE_CLICK
                    else -> return
                }))
                return
            }
            val ms = when (kind) {
                "tick" -> 10L
                "light" -> 15L
                "medium" -> 25L
                "success" -> 40L
                else -> return
            }
            if (Build.VERSION.SDK_INT >= 26) v.vibrate(VibrationEffect.createOneShot(ms, VibrationEffect.DEFAULT_AMPLITUDE))
            else v.vibrate(ms)
        }
    }

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        web = WebView(this)
        setContentView(web)
        web.settings.javaScriptEnabled = true
        web.settings.domStorageEnabled = true
        web.settings.cacheMode = WebSettings.LOAD_DEFAULT
        web.addJavascriptInterface(Haptics(), "AndroidHaptics")
        val home = Uri.parse(BuildConfig.APP_URL)
        web.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                if (request.url.host == home.host) return false
                startActivity(Intent(Intent.ACTION_VIEW, request.url))   // 外部連結用瀏覽器開
                return true
            }

            override fun onReceivedError(view: WebView, request: WebResourceRequest, error: WebResourceError) {
                if (request.isForMainFrame) {
                    view.loadDataWithBaseURL(null,
                        "<html><body style='font-family:sans-serif;padding:24px'><h3>連唔到網絡</h3>" +
                            "<p>檢查網絡之後重開 app。</p></body></html>", "text/html", "utf-8", null)
                }
            }
        }
        if (savedInstanceState != null) web.restoreState(savedInstanceState) else web.loadUrl(BuildConfig.APP_URL)
    }

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        web.saveState(outState)
    }

    @Deprecated("Deprecated in Java")
    override fun onBackPressed() {
        if (web.canGoBack()) web.goBack() else super.onBackPressed()
    }
}
