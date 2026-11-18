import com.erfan.standaloneai.LiteRtLmBridge;
import com.google.ai.edge.litertlm.StubControl;

import java.io.File;

/** Drives LiteRtLmBridge against the stand-in engine. Modes: "ok" (the engine API as expected) and "drift" (EngineConfig changed shape). */
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

    public static void main(String[] args) throws Exception {
        String mode = args.length > 0 ? args[0] : "ok";
        File model = File.createTempFile("brain", ".litertlm");
        model.deleteOnExit();
        StubControl.reset();
        if (mode.equals("drift")) {
            String r = LiteRtLmBridge.load(model.getAbsolutePath(), 2048);
            check("drift_is_api_mismatch", r.startsWith("ERR\napi_mismatch\n") && r.contains("EngineConfig"), r);
            check("drift_not_loaded", !LiteRtLmBridge.isLoaded(), "loaded");
            System.out.println("DONE failures=" + failures);
            System.exit(failures == 0 ? 0 : 1);
        }

        check("present", LiteRtLmBridge.isPresent() && LiteRtLmBridge.describe().contains("present=true")
                && LiteRtLmBridge.describe().contains("Engine=true"), LiteRtLmBridge.describe());
        String r = LiteRtLmBridge.chat("", "", "سلام", 16);
        check("chat_before_load", r.startsWith("ERR\nnot_loaded\n"), r);
        r = LiteRtLmBridge.load("/nonexistent/dir/x.litertlm", 2048);
        check("missing_file", r.startsWith("ERR\nmodel_file_unreadable\n"), r);
        r = LiteRtLmBridge.load("", 2048);
        check("empty_path", r.startsWith("ERR\nbad_arguments\n"), r);

        r = LiteRtLmBridge.load(model.getAbsolutePath(), 2048);
        check("load_ok", r.equals("OK\nloaded") && LiteRtLmBridge.isLoaded(), r);
        check("load_built_the_config_as_documented", logHas("engine:path=" + model.getAbsolutePath() + "|backend=CPU|maxNumTokens=2048")
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
