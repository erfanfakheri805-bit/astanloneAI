import com.erfan.standaloneai.LiteRtLmBridge;
import com.google.ai.edge.litertlm.StubControl;

import java.io.File;

/** Drives LiteRtLmBridge against the stand-in engine. Modes: "ok" (the engine API as expected), "drift" (EngineConfig changed shape) and
 * "probe <verdict> <piece> [huge]" (a variant the test made from the stand-ins: the pre-download probe must give exactly that verdict). */
public final class OkMain {
    private static int failures;

    private static void check(String name, boolean condition, String detail) {
        if (condition) {
            System.out.println("PASS " + name);
        } else {
            failures++;
            System.out.println("FAIL " + name + " :: " + detail);
        }
    }

    private static boolean logHas(String needle) {
        synchronized (StubControl.LOG) {
            for (String line : StubControl.LOG) {
                if (line.contains(needle)) {
                    return true;
                }
            }
        }
        return false;
    }

    private static String q(String history, String user, int max) {
        return LiteRtLmBridge.chat("سیستم", history, user, max);
    }

    /** Starts one slow answer in a worker thread; its result lands in box[0]. */
    private static Thread slowAnswer(final String[] box, final String text) {
        Thread worker = new Thread(new Runnable() {
            public void run() {
                box[0] = q("", text, 16);
            }
        });
        worker.start();
        return worker;
    }

    public static void main(String[] args) throws Exception {
        String mode = args.length > 0 ? args[0] : "ok";
        File model = File.createTempFile("brain", ".litertlm");
        model.deleteOnExit();
        StubControl.reset();
        if (mode.equals("drift")) {
            String r = LiteRtLmBridge.load(model.getAbsolutePath(), 2048);
            check("drift_is_api_mismatch", r.startsWith("ERR\napi_mismatch\n") && r.contains("EngineConfig"), r);
            check("drift_not_loaded", !LiteRtLmBridge.isLoaded(), "loaded");
            String probe = LiteRtLmBridge.probe();                       // the same drift is found BEFORE any model is fetched
            check("drift_probe_names_the_missing_piece", probe.equals("ERR\napi_mismatch\nEngineConfig(String, Backend)"), probe);
            String listing = LiteRtLmBridge.api();
            check("drift_api_lists_what_the_engine_really_has", listing.contains("EngineConfig:") && listing.contains("<init>(String,int,long)"), listing);
            System.out.println("DONE failures=" + failures);
            System.exit(failures == 0 ? 0 : 1);
        }

        if (mode.equals("probe")) {          // a variant made by the test: args[1] = the verdict the probe must give, args[2] = the piece it must name
            String want = args[1].equals("ok") ? "OK\nready" : "ERR\n" + args[1] + "\n" + args[2];
            boolean huge = args.length > 3 && args[3].equals("huge");
            String probe = LiteRtLmBridge.probe();
            check("probe_gives_this_verdict", probe.equals(want), probe);
            check("probe_loaded_nothing_and_logged_nothing", !LiteRtLmBridge.isLoaded() && !logHas("initialize") && !logHas("engine:"),
                    String.valueOf(StubControl.LOG));
            String listing = LiteRtLmBridge.api();
            check("api_listing_is_there_and_capped", listing.contains("Engine:") && (huge ? listing.length() == 6000 : listing.length() < 6001),
                    "length=" + listing.length());
            if (args[1].equals("ok")) {      // an "ok" has to be TRUE: the engine then really loads and really answers
                String r = LiteRtLmBridge.load(model.getAbsolutePath(), 512);
                check("ok_means_it_really_loads", r.equals("OK\nloaded"), r);
                r = q("", "سلام", 16);
                check("ok_means_it_really_answers", r.equals("OK\nپاسخ|سلام|earlier=0"), r);
                LiteRtLmBridge.unload();
            }
            System.out.println("DONE failures=" + failures);
            System.exit(failures == 0 ? 0 : 1);
        }

        check("present", LiteRtLmBridge.isPresent() && LiteRtLmBridge.describe().contains("present=true")
                && LiteRtLmBridge.describe().contains("Engine=true"), LiteRtLmBridge.describe());
        check("probe_ok_with_an_engine_shaped_as_expected", LiteRtLmBridge.probe().equals("OK\nready"), LiteRtLmBridge.probe());
        String listing = LiteRtLmBridge.api();
        check("api_lists_the_engine_classes", listing.contains("Engine:") && listing.contains("initialize()") && listing.contains("createConversation(")
                && listing.contains("EngineConfig:") && listing.contains("Companion{") && listing.length() < 6001, listing);
        check("probe_loaded_nothing_and_logged_nothing", !LiteRtLmBridge.isLoaded() && !logHas("initialize"), StubControl.LOG.toString());
        String r = LiteRtLmBridge.chat("", "", "سلام", 16);
        check("chat_before_load", r.startsWith("ERR\nnot_loaded\n"), r);
        r = LiteRtLmBridge.load("/nonexistent/dir/x.litertlm", 2048);
        check("missing_file", r.startsWith("ERR\nmodel_file_unreadable\n"), r);
        r = LiteRtLmBridge.load("", 2048);
        check("empty_path", r.startsWith("ERR\nbad_arguments\n"), r);

        r = LiteRtLmBridge.load(model.getAbsolutePath(), 2048);
        check("load_ok", r.equals("OK\nloaded") && LiteRtLmBridge.isLoaded(), r);
        check("load_built_the_config_as_documented", logHas("engine:path=" + model.getAbsolutePath() + "|backend=CPU|maxNumTokens=2048")
                && logHas("config:path=" + model.getAbsolutePath() + "|maxNumTokens=2048|maxNumImages=null|cacheDir=null|vision=null|audio=null")
                && logHas("initialize"), StubControl.LOG.toString());

        r = q("u1\u001Fa1\u001Eu2\u001Fa2", "سلام؟", 64);
        check("chat_answer", r.equals("OK\nپاسخ|سلام؟|earlier=4"), r);
        check("chat_history_order_and_options", logHas("conversation:system=سیستم|initial=user:u1;assistant:a1;user:u2;assistant:a2;|maxOut=64|thinkingOff=true|sampler=40/0.7")
                && logHas("send:سلام؟|max=64"), StubControl.LOG.toString());
        check("conversation_closed_after_answer", StubControl.closedConversations == 1, "closed=" + StubControl.closedConversations);

        StubControl.LOG.clear();
        r = LiteRtLmBridge.chat("", "", "hi", 32);
        check("chat_without_system_or_history", r.equals("OK\nپاسخ|hi|earlier=0") && logHas("conversation:system=|initial=|"), r + " " + StubControl.LOG);

        StringBuilder many = new StringBuilder();
        for (int i = 1; i <= 9; i++) {
            many.append(i == 1 ? "" : "\u001E").append("q").append(i).append('\u001F').append("a").append(i);
        }
        StubControl.LOG.clear();
        r = q(many.toString(), "x", 16);
        check("history_limited_to_last_turns", r.equals("OK\nپاسخ|x|earlier=12") && logHas("initial=user:q4;assistant:a4;") && !logHas("user:q3;"), r + StubControl.LOG);
        r = q("garbage\u001Eok\u001Fyes\u001E\u001F\u001Ex\u001F", "y", 16);
        check("bad_history_records_are_skipped", r.equals("OK\nپاسخ|y|earlier=2"), r);

        r = LiteRtLmBridge.chat("s", "", "   ", 10);
        check("blank_question_refused", r.startsWith("ERR\nbad_arguments\n"), r);
        StringBuilder big = new StringBuilder();
        for (int i = 0; i < 9000; i++) {
            big.append('a');
        }
        r = LiteRtLmBridge.chat("s", "", big.toString(), 10);
        check("huge_question_refused", r.startsWith("ERR\nbad_arguments\n"), r.substring(0, 20));

        StubControl.reset();
        StubControl.failRichConfig = true;
        r = q("", "fallback1", 48);
        check("falls_back_to_the_basic_config", r.equals("OK\nپاسخ|fallback1|earlier=0") && logHas("maxOut=null|thinkingOff=false") && logHas("send:fallback1|max=48"),
                r + StubControl.LOG);
        StubControl.reset();
        StubControl.failCreateWithThinking = true;
        r = q("", "fallback2", 48);
        check("falls_back_when_the_model_refuses_thinking_off", r.startsWith("OK\n") && logHas("thinkingOff=false"), r + StubControl.LOG);
        StubControl.reset();
        StubControl.failRichConfig = true;
        StubControl.failBasicConfig = true;
        r = q("", "fallback3", 48);
        check("falls_back_to_the_bare_config", r.startsWith("OK\n") && logHas("conversation:system=سیستم"), r + StubControl.LOG);
        StubControl.reset();

        StubControl.answerDelayMs = 5000;
        final String[] box = new String[1];
        Thread worker = new Thread(new Runnable() {
            public void run() {
                box[0] = q("", "slow", 16);
            }
        });
        long t0 = System.currentTimeMillis();
        worker.start();
        Thread.sleep(150);
        LiteRtLmBridge.cancel();
        worker.join(3000);
        long took = System.currentTimeMillis() - t0;
        check("cancel_ends_the_answer_quickly", box[0] != null && box[0].startsWith("ERR\ncancelled\n") && took < 2500 && logHas("cancelProcess"),
                box[0] + " took=" + took);
        StubControl.reset();
        r = q("", "after cancel", 16);
        check("works_again_after_a_cancel", r.startsWith("OK\n"), r);

        // ---- a stop that arrives a moment too early (the engine has not started to generate) is not lost: it is repeated until the answer has ended
        StubControl.reset();
        StubControl.answerDelayMs = 8000;
        StubControl.ignoreCancels = 2;
        final String[] box2 = new String[1];
        t0 = System.currentTimeMillis();
        Thread early = slowAnswer(box2, "early stop");
        Thread.sleep(150);
        LiteRtLmBridge.cancel();
        early.join(5000);
        took = System.currentTimeMillis() - t0;
        int callsAtEnd = StubControl.cancelCalls;
        check("a_stop_that_came_too_early_is_repeated_until_it_takes_effect",
                box2[0] != null && box2[0].startsWith("ERR\ncancelled\n") && took >= 480 && took < 3000 && callsAtEnd == 3,
                box2[0] + " took=" + took + " calls=" + callsAtEnd + " (one request at once, then one every 200 ms: the third takes effect after about 550 ms)");
        Thread.sleep(700);
        check("the_repeating_stops_with_the_answer", StubControl.cancelCalls == callsAtEnd && StubControl.cancelAfterClose == 0,
                "calls=" + StubControl.cancelCalls + " atEnd=" + callsAtEnd + " afterClose=" + StubControl.cancelAfterClose);

        // ---- the conversation is never closed while a stop request is still being made on it
        StubControl.reset();
        StubControl.answerDelayMs = 8000;
        StubControl.cancelSlowMs = 80;
        final String[] box3 = new String[1];
        Thread slowStop = slowAnswer(box3, "slow stop");
        Thread.sleep(150);
        LiteRtLmBridge.cancel();
        slowStop.join(5000);
        Thread.sleep(500);
        check("the_conversation_is_not_closed_while_a_stop_request_is_being_made",
                box3[0] != null && box3[0].startsWith("ERR\ncancelled\n") && !StubControl.closedWhileCancelling && StubControl.cancelAfterClose == 0
                        && StubControl.closedConversations == 1,
                box3[0] + " closedWhile=" + StubControl.closedWhileCancelling + " afterClose=" + StubControl.cancelAfterClose + " closed=" + StubControl.closedConversations);

        // ---- the same when the request that takes effect is a REPEATED one (the first was lost) and it is slow
        StubControl.reset();
        StubControl.answerDelayMs = 8000;
        StubControl.ignoreCancels = 1;
        StubControl.cancelSlowMs = 80;
        final String[] box4 = new String[1];
        Thread slowRepeat = slowAnswer(box4, "slow repeated stop");
        Thread.sleep(150);
        LiteRtLmBridge.cancel();
        slowRepeat.join(5000);
        Thread.sleep(500);
        check("the_closing_also_waits_for_a_repeated_stop_request",
                box4[0] != null && box4[0].startsWith("ERR\ncancelled\n") && !StubControl.closedWhileCancelling && StubControl.cancelAfterClose == 0
                        && StubControl.cancelCalls == 2 && StubControl.closedConversations == 1,
                box4[0] + " closedWhile=" + StubControl.closedWhileCancelling + " afterClose=" + StubControl.cancelAfterClose + " calls=" + StubControl.cancelCalls
                        + " closed=" + StubControl.closedConversations);

        // ---- pressing stop again and again does not start more and more repeating threads (one per answer)
        StubControl.reset();
        StubControl.answerDelayMs = 8000;
        StubControl.ignoreCancels = 1000;
        final String[] box5 = new String[1];
        Thread pressed = slowAnswer(box5, "pressed many times");
        Thread.sleep(150);
        for (int i = 0; i < 4; i++) {
            LiteRtLmBridge.cancel();
        }
        Thread.sleep(1050);
        int callsWhileLost = StubControl.cancelCalls;
        StubControl.ignoreCancels = 0;
        pressed.join(5000);
        check("pressing_stop_again_does_not_add_more_repeaters",
                box5[0] != null && box5[0].startsWith("ERR\ncancelled\n") && callsWhileLost >= 4 + 3 && callsWhileLost <= 4 + 7,
                box5[0] + " calls while the stop was lost=" + callsWhileLost + " (4 pressed + about 5 repeated by ONE thread)");

        // ---- a stop that comes while the conversation is being made: nothing is generated at all
        StubControl.reset();
        StubControl.duringCreate = new Runnable() {
            public void run() {
                LiteRtLmBridge.cancel();
            }
        };
        r = q("", "never generated", 16);
        check("a_stop_while_the_conversation_is_made_generates_nothing", r.startsWith("ERR\ncancelled\n") && !logHas("send:") && StubControl.cancelCalls == 0,
                r + " " + StubControl.LOG);

        // ---- a stop with nothing running is harmless and leaves nothing behind
        StubControl.reset();
        LiteRtLmBridge.cancel();
        Thread.sleep(300);
        r = q("", "after an idle stop", 16);
        check("a_stop_with_nothing_running_is_harmless", StubControl.cancelCalls == 0 && r.startsWith("OK\n"), r + " calls=" + StubControl.cancelCalls);
        StubControl.reset();

        r = LiteRtLmBridge.unload();
        check("unload", r.equals("OK\nunloaded") && !LiteRtLmBridge.isLoaded() && StubControl.closedEngines == 1, r + " closed=" + StubControl.closedEngines);
        r = q("", "x", 8);
        check("chat_after_unload", r.startsWith("ERR\nnot_loaded\n"), r);

        StubControl.reset();
        StubControl.failInit = new OutOfMemoryError("boom");
        r = LiteRtLmBridge.load(model.getAbsolutePath(), 2048);
        check("init_out_of_memory", r.startsWith("ERR\nout_of_memory\n") && !LiteRtLmBridge.isLoaded(), r);
        StubControl.failInit = new UnsatisfiedLinkError("dlopen failed: liblitertlm_jni.so");
        r = LiteRtLmBridge.load(model.getAbsolutePath(), 2048);
        check("init_native_missing", r.startsWith("ERR\nnative_missing\n") && r.contains("dlopen"), r);
        StubControl.failInit = new IllegalStateException("bad model");
        r = LiteRtLmBridge.load(model.getAbsolutePath(), 2048);
        check("init_other_failure", r.startsWith("ERR\nengine_load_failed\n") && r.contains("IllegalStateException"), r);
        StubControl.failInit = null;

        r = LiteRtLmBridge.load(model.getAbsolutePath(), 100);
        check("tokens_are_clamped_up", r.equals("OK\nloaded") && logHas("maxNumTokens=256"), r + StubControl.LOG);
        r = LiteRtLmBridge.load(model.getAbsolutePath(), 4096);
        check("reload_releases_the_first_engine", r.equals("OK\nloaded") && StubControl.closedEngines >= 1 && logHas("maxNumTokens=4096"),
                r + " closed=" + StubControl.closedEngines);
        LiteRtLmBridge.unload();

        System.out.println("DONE failures=" + failures);
        System.exit(failures == 0 ? 0 : 1);
    }
}
