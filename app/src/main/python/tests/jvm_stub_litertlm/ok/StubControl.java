package com.google.ai.edge.litertlm;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/** TEST STAND-IN control panel: what the stand-in engine saw, and failures to inject. Not part of the real library. */
public final class StubControl {
    public static final List<String> LOG = Collections.synchronizedList(new ArrayList<String>());
    public static volatile Throwable failInit;
    public static volatile boolean failRichConfig;
    public static volatile boolean failBasicConfig;
    public static volatile boolean failCreateWithThinking;
    public static volatile long answerDelayMs;
    public static volatile boolean cancelRequested;
    public static volatile String lastModelPath = "";
    public static volatile int closedConversations;
    public static volatile int closedEngines;

    private StubControl() {
    }

    public static void reset() {
        LOG.clear();
        failInit = null;
        failRichConfig = false;
        failBasicConfig = false;
        failCreateWithThinking = false;
        answerDelayMs = 0;
        cancelRequested = false;
        lastModelPath = "";
        closedConversations = 0;
        closedEngines = 0;
    }
}
