package com.chaquo.python;

/** TEST STAND-IN for Chaquopy's Python (the real one is added by the Chaquopy plugin when the APK is built). Python is never started here. */
public class Python {
    public static boolean isStarted() {
        return false;
    }

    public static Python getInstance() {
        return new Python();
    }

    public PyObject getModule(String name) {
        return new PyObject();
    }
}
