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
    public static volatile int ignoreCancels;              // the first N cancelProcess() calls do nothing (the engine had not started to generate yet)
    public static volatile int cancelCalls;                // how many times cancelProcess() was called
    public static volatile long cancelSlowMs;              // every cancelProcess() call takes this long
    public static volatile boolean closedWhileCancelling;  // a conversation was closed while a cancelProcess() call on it was still running
    public static volatile int cancelAfterClose;           // cancelProcess() calls that reached a conversation which was already closed
    public static volatile Runnable duringCreate;          // runs inside Engine.createConversation (a stop that comes while the conversation is made)

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
        ignoreCancels = 0;
        cancelCalls = 0;
        cancelSlowMs = 0;
        closedWhileCancelling = false;
        cancelAfterClose = 0;
        duringCreate = null;
    }
}
