package com.chaquo.python;

/** TEST STAND-IN for Chaquopy's PyObject (the real one is added by the Chaquopy plugin when the APK is built). */
public class PyObject {
    public PyObject callAttr(String key, Object... args) {
        return this;
    }

    @Override
    public String toString() {
        return "";
    }
}
