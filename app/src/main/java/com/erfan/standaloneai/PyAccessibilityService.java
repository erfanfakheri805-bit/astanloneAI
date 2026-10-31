package com.erfan.standaloneai;

import android.accessibilityservice.AccessibilityService;
import android.content.Intent;
import android.graphics.Rect;
import android.os.Build;
import android.os.Bundle;
import android.view.accessibility.AccessibilityEvent;
import android.view.accessibility.AccessibilityNodeInfo;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

/**
 * Prompt 958: the screen door of the assistant - the one way it can "go into" another app the way a person does
 * (read what is on the screen, type into a field, press a button).
 *
 * Android allows this ONLY through an accessibility service that THE USER switches on in Android's settings; this
 * class never enables itself. It does nothing on its own: it has no timer, no network and no background loop, and
 * it keeps no text. Every call below is made by the Python side (native_bridge.screen.ScreenDoor), which first
 * checks that the user allowed that very app for this task and refuses the system apps (settings, package
 * installer, permission controller, store). The password fields are never read and never written here either.
 *
 * All the methods are static so that Python can reach them through the class name; each one answers a plain value
 * (boolean / String) and never throws.
 */
public class PyAccessibilityService extends AccessibilityService {

    private static final int MAX_DEPTH = 40;
    private static final int MAX_NODES_HARD = 250;
    private static final int MAX_TEXT = 4000;
    private static final int MAX_DESC = 300;
    private static final int MAX_ANCESTORS = 6;
    private static final int MAX_SEARCH = 600;
    private static final String SYSTEM_UI = "com.android.systemui";
    private static final String INPUT_WINDOW = "android.inputmethodservice.SoftInputWindow";

    private static volatile PyAccessibilityService instance;
    private static volatile String lastPackage = "";

    // ------------------------------------------------------------------------------------------ service life cycle
    @Override
    protected void onServiceConnected() {
        super.onServiceConnected();
        instance = this;
    }

    @Override
    public void onAccessibilityEvent(AccessibilityEvent event) {
        if (event == null || event.getEventType() != AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED) {
            return;
        }
        // Only the NAME of the app that came to the front is remembered - no text, no content.
        CharSequence pkg = event.getPackageName();
        CharSequence cls = event.getClassName();
        if (pkg == null || SYSTEM_UI.contentEquals(pkg) || (cls != null && INPUT_WINDOW.contentEquals(cls))) {
            return;
        }
        lastPackage = pkg.toString();
    }

    @Override
    public void onInterrupt() {
        // Nothing is running that could be interrupted.
    }

    @Override
    public boolean onUnbind(Intent intent) {
        if (instance == this) {
            instance = null;
        }
        return super.onUnbind(intent);
    }

    @Override
    public void onDestroy() {
        if (instance == this) {
            instance = null;
        }
        super.onDestroy();
    }

    // ------------------------------------------------------------------------------------------ what Python asks
    /** True while the user has the service switched on in Android's settings. */
    public static boolean isConnected() {
        return instance != null;
    }

    /** The package name of the app in front ("" when unknown). */
    public static String activePackage() {
        PyAccessibilityService service = instance;
        if (service == null) {
            return "";
        }
        AccessibilityNodeInfo root = null;
        try {
            root = service.getRootInActiveWindow();
            if (root != null && root.getPackageName() != null) {
                return root.getPackageName().toString();
            }
        } catch (RuntimeException e) {
            // fall back to the remembered name below
        } finally {
            recycle(root);
        }
        return lastPackage;
    }

    /**
     * The screen as one JSON text: {"package", "truncated", "nodes":[{"t","d","id","c","k","e","f","s","p","b":[l,t,r,b]}]}.
     * Only nodes that show text or can be used are listed; a password field has no text. Null when there is no window.
     */
    public static String readScreen(int maxNodes) {
        PyAccessibilityService service = instance;
        if (service == null) {
            return null;
        }
        AccessibilityNodeInfo root = null;
        try {
            root = service.getRootInActiveWindow();
            if (root == null) {
                return null;
            }
            int limit = Math.max(1, Math.min(maxNodes, MAX_NODES_HARD));
            JSONArray nodes = new JSONArray();
            boolean[] truncated = new boolean[] {false};
            walk(root, nodes, limit, truncated, 0);
            JSONObject out = new JSONObject();
            out.put("package", root.getPackageName() == null ? "" : root.getPackageName().toString());
            out.put("truncated", truncated[0]);
            out.put("nodes", nodes);
            return out.toString();
        } catch (JSONException e) {
            return null;
        } catch (RuntimeException e) {
            return null;
        } finally {
            recycle(root);
        }
    }

    /** Press the first (or, with {@code last}, the LAST) visible node whose text or description contains {@code text}. */
    public static boolean clickNode(String text, boolean exact, String viewId, boolean last) {
        PyAccessibilityService service = instance;
        if (service == null) {
            return false;
        }
        String wanted = text == null ? "" : text.trim();
        String id = viewId == null ? "" : viewId.trim();
        if (wanted.isEmpty() && id.isEmpty()) {
            return false;
        }
        AccessibilityNodeInfo root = null;
        List<AccessibilityNodeInfo> found = new ArrayList<AccessibilityNodeInfo>();
        try {
            root = service.getRootInActiveWindow();
            if (root == null) {
                return false;
            }
            List<AccessibilityNodeInfo> raw = id.isEmpty()
                    ? root.findAccessibilityNodeInfosByText(wanted)
                    : root.findAccessibilityNodeInfosByViewId(id);
            if (raw == null) {
                return false;
            }
            found.addAll(raw);
            List<AccessibilityNodeInfo> usable = new ArrayList<AccessibilityNodeInfo>();
            for (AccessibilityNodeInfo node : found) {
                if (node == null || !node.isVisibleToUser() || node.isPassword()) {
                    continue;
                }
                if (!wanted.isEmpty() && !matches(node, wanted, exact)) {
                    continue;
                }
                usable.add(node);
            }
            if (usable.isEmpty()) {
                return false;
            }
            AccessibilityNodeInfo chosen = last ? usable.get(usable.size() - 1) : usable.get(0);
            return clickSelfOrAncestor(chosen);
        } catch (RuntimeException e) {
            return false;
        } finally {
            for (AccessibilityNodeInfo node : found) {
                recycle(node);
            }
            recycle(root);
        }
    }

    /** Write {@code text} into an editable field (chosen by id, else by hint, else the focused / first one). Never a password field. */
    public static boolean setText(String hint, String viewId, String text) {
        PyAccessibilityService service = instance;
        if (service == null || text == null) {
            return false;
        }
        AccessibilityNodeInfo root = null;
        List<AccessibilityNodeInfo> editable = new ArrayList<AccessibilityNodeInfo>();
        try {
            root = service.getRootInActiveWindow();
            if (root == null) {
                return false;
            }
            String id = viewId == null ? "" : viewId.trim();
            String wantedHint = hint == null ? "" : hint.trim();
            if (!id.isEmpty()) {
                List<AccessibilityNodeInfo> byId = root.findAccessibilityNodeInfosByViewId(id);
                if (byId != null) {
                    editable.addAll(byId);
                }
            } else {
                collectEditable(root, editable, 0, new int[] {0});
            }
            AccessibilityNodeInfo target = pickEditable(editable, wantedHint);
            if (target == null || target.isPassword()) {
                return false;
            }
            target.performAction(AccessibilityNodeInfo.ACTION_FOCUS);
            Bundle arguments = new Bundle();
            arguments.putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, text);
            return target.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, arguments);
        } catch (RuntimeException e) {
            return false;
        } finally {
            for (AccessibilityNodeInfo node : editable) {
                recycle(node);
            }
            recycle(root);
        }
    }

    /** One of the four system keys: back, home, recents, notifications. */
    public static boolean globalAction(String name) {
        PyAccessibilityService service = instance;
        if (service == null || name == null) {
            return false;
        }
        int action;
        if ("back".equals(name)) {
            action = GLOBAL_ACTION_BACK;
        } else if ("home".equals(name)) {
            action = GLOBAL_ACTION_HOME;
        } else if ("recents".equals(name)) {
            action = GLOBAL_ACTION_RECENTS;
        } else if ("notifications".equals(name)) {
            action = GLOBAL_ACTION_NOTIFICATIONS;
        } else {
            return false;
        }
        try {
            return service.performGlobalAction(action);
        } catch (RuntimeException e) {
            return false;
        }
    }

    /** Scroll the first scrollable area of the front app one page. */
    public static boolean scroll(boolean forward) {
        PyAccessibilityService service = instance;
        if (service == null) {
            return false;
        }
        AccessibilityNodeInfo root = null;
        List<AccessibilityNodeInfo> scrollable = new ArrayList<AccessibilityNodeInfo>();
        try {
            root = service.getRootInActiveWindow();
            if (root == null) {
                return false;
            }
            collectScrollable(root, scrollable, 0, new int[] {0});
            if (scrollable.isEmpty()) {
                return false;
            }
            int action = forward ? AccessibilityNodeInfo.ACTION_SCROLL_FORWARD : AccessibilityNodeInfo.ACTION_SCROLL_BACKWARD;
            return scrollable.get(0).performAction(action);
        } catch (RuntimeException e) {
            return false;
        } finally {
            for (AccessibilityNodeInfo node : scrollable) {
                recycle(node);
            }
            recycle(root);
        }
    }

    // ------------------------------------------------------------------------------------------ helpers
    private static void walk(AccessibilityNodeInfo node, JSONArray out, int limit, boolean[] truncated, int depth)
            throws JSONException {
        if (node == null) {
            return;
        }
        if (out.length() >= limit) {
            truncated[0] = true;
            return;
        }
        if (node.isVisibleToUser()) {
            JSONObject item = describe(node);
            if (item != null) {
                out.put(item);
            }
        }
        int count = node.getChildCount();
        if (depth >= MAX_DEPTH) {
            if (count > 0) {
                truncated[0] = true;
            }
            return;
        }
        for (int i = 0; i < count; i++) {
            if (out.length() >= limit) {
                truncated[0] = true;
                return;
            }
            AccessibilityNodeInfo child = node.getChild(i);
            if (child == null) {
                continue;
            }
            try {
                walk(child, out, limit, truncated, depth + 1);
            } finally {
                recycle(child);
            }
        }
    }

    private static JSONObject describe(AccessibilityNodeInfo node) throws JSONException {
        boolean password = node.isPassword();
        CharSequence text = node.getText();
        CharSequence desc = node.getContentDescription();
        boolean clickable = node.isClickable();
        boolean editable = node.isEditable();
        boolean scrollable = node.isScrollable();
        boolean hasText = (text != null && text.length() > 0) || (desc != null && desc.length() > 0);
        if (!hasText && !clickable && !editable && !scrollable && !password) {
            return null;                                   // an empty layout container tells nothing
        }
        JSONObject o = new JSONObject();
        o.put("t", (password || text == null) ? "" : clip(text.toString(), MAX_TEXT));
        o.put("d", (password || desc == null) ? "" : clip(desc.toString(), MAX_DESC));
        String id = node.getViewIdResourceName();
        o.put("id", id == null ? "" : clip(id, 120));
        CharSequence cls = node.getClassName();
        o.put("c", cls == null ? "" : clip(cls.toString(), 80));
        o.put("k", clickable);
        o.put("e", editable);
        o.put("f", node.isFocused());
        o.put("s", scrollable);
        o.put("p", password);
        Rect box = new Rect();
        node.getBoundsInScreen(box);
        JSONArray bounds = new JSONArray();
        bounds.put(box.left);
        bounds.put(box.top);
        bounds.put(box.right);
        bounds.put(box.bottom);
        o.put("b", bounds);
        return o;
    }

    private static boolean matches(AccessibilityNodeInfo node, String wanted, boolean exact) {
        String needle = wanted.toLowerCase(Locale.ROOT);
        CharSequence text = node.getText();
        CharSequence desc = node.getContentDescription();
        return same(text, needle, exact) || same(desc, needle, exact);
    }

    private static boolean same(CharSequence value, String needle, boolean exact) {
        if (value == null) {
            return false;
        }
        String lower = value.toString().trim().toLowerCase(Locale.ROOT);
        return exact ? lower.equals(needle) : lower.contains(needle);
    }

    private static boolean clickSelfOrAncestor(AccessibilityNodeInfo node) {
        AccessibilityNodeInfo current = node;
        boolean owned = false;                              // nodes we obtained with getParent() must be recycled by us
        try {
            for (int level = 0; level <= MAX_ANCESTORS && current != null; level++) {
                if (current.isClickable() && current.isEnabled()) {
                    return current.performAction(AccessibilityNodeInfo.ACTION_CLICK);
                }
                AccessibilityNodeInfo parent = current.getParent();
                if (owned) {
                    recycle(current);
                }
                current = parent;
                owned = true;
            }
            return false;
        } finally {
            if (owned) {
                recycle(current);
            }
        }
    }

    private static void collectEditable(AccessibilityNodeInfo node, List<AccessibilityNodeInfo> out, int depth, int[] seen) {
        if (node == null || depth > MAX_DEPTH || seen[0] >= MAX_SEARCH) {
            return;
        }
        seen[0]++;
        int count = node.getChildCount();
        for (int i = 0; i < count; i++) {
            AccessibilityNodeInfo child = node.getChild(i);
            if (child == null) {
                continue;
            }
            boolean keep = false;
            try {
                if (child.isVisibleToUser() && child.isEditable() && !child.isPassword()) {
                    out.add(child);
                    keep = true;
                }
                collectEditable(child, out, depth + 1, seen);
            } finally {
                if (!keep) {
                    recycle(child);
                }
            }
        }
    }

    private static void collectScrollable(AccessibilityNodeInfo node, List<AccessibilityNodeInfo> out, int depth, int[] seen) {
        if (node == null || depth > MAX_DEPTH || seen[0] >= MAX_SEARCH || !out.isEmpty()) {
            return;
        }
        seen[0]++;
        int count = node.getChildCount();
        for (int i = 0; i < count && out.isEmpty(); i++) {
            AccessibilityNodeInfo child = node.getChild(i);
            if (child == null) {
                continue;
            }
            boolean keep = false;
            try {
                if (child.isVisibleToUser() && child.isScrollable()) {
                    out.add(child);
                    keep = true;
                } else {
                    collectScrollable(child, out, depth + 1, seen);
                }
            } finally {
                if (!keep) {
                    recycle(child);
                }
            }
        }
    }

    private static AccessibilityNodeInfo pickEditable(List<AccessibilityNodeInfo> candidates, String hint) {
        AccessibilityNodeInfo focused = null;
        AccessibilityNodeInfo first = null;
        String needle = hint.toLowerCase(Locale.ROOT);
        for (AccessibilityNodeInfo node : candidates) {
            if (node == null || node.isPassword()) {
                continue;
            }
            if (!needle.isEmpty() && hintMatches(node, needle)) {
                return node;
            }
            if (first == null) {
                first = node;
            }
            if (focused == null && node.isFocused()) {
                focused = node;
            }
        }
        if (!needle.isEmpty()) {
            return null;                                    // a hint was asked for and nothing carries it: never guess
        }
        return focused != null ? focused : first;
    }

    private static boolean hintMatches(AccessibilityNodeInfo node, String needle) {
        if (same(node.getText(), needle, false) || same(node.getContentDescription(), needle, false)) {
            return true;
        }
        if (Build.VERSION.SDK_INT >= 26) {
            return same(node.getHintText(), needle, false);
        }
        return false;
    }

    private static String clip(String value, int limit) {
        return value.length() <= limit ? value : value.substring(0, limit);
    }

    @SuppressWarnings("deprecation")
    private static void recycle(AccessibilityNodeInfo node) {
        if (node == null) {
            return;
        }
        try {
            node.recycle();                                  // a no-op since Android 13; needed on older versions
        } catch (RuntimeException e) {
            // already recycled: nothing to do
        }
    }
}
