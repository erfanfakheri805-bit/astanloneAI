import com.erfan.standaloneai.LiteRtLmBridge;

import java.io.File;

/** Runs LiteRtLmBridge with NO engine classes at all (an APK built without the engine): nothing may throw. */
public final class AbsentMain {
    private static int failures;

    private static void check(String name, boolean condition, String detail) {
        if (condition) {
            System.out.println("PASS " + name);
        } else {
            failures++;
            System.out.println("FAIL " + name + " :: " + detail);
        }
    }

    public static void main(String[] args) throws Exception {
        File model = File.createTempFile("brain", ".litertlm");
        model.deleteOnExit();
        check("not_present", !LiteRtLmBridge.isPresent() && LiteRtLmBridge.describe().contains("present=false"), LiteRtLmBridge.describe());
        check("probe_says_dependency_missing", LiteRtLmBridge.probe().equals("ERR\ndependency_missing\nengine"), LiteRtLmBridge.probe());
        String listing = LiteRtLmBridge.api();
        check("api_listing_never_throws_without_an_engine", listing.contains("Engine: -") && listing.contains("Message: -"), listing);
        String r = LiteRtLmBridge.load(model.getAbsolutePath(), 2048);
        check("load_says_dependency_missing", r.startsWith("ERR\ndependency_missing\n") && !LiteRtLmBridge.isLoaded(), r);
        r = LiteRtLmBridge.chat("", "", "سلام", 8);
        check("chat_says_not_loaded", r.startsWith("ERR\nnot_loaded\n"), r);
        LiteRtLmBridge.cancel();
        r = LiteRtLmBridge.unload();
        check("unload_is_harmless", r.equals("OK\nunloaded"), r);
        System.out.println("DONE failures=" + failures);
        System.exit(failures == 0 ? 0 : 1);
    }
}
