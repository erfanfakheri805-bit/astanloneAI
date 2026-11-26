package com.erfan.standaloneai;

import java.io.File;
import java.lang.reflect.Constructor;
import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Map;

/**
 * LiteRtLmBridge - the app's narrow door to Google's LiteRT-LM engine (the language model that runs ON the phone).
 *
 * Prompt 959 (stage B, "own brain"): Python (model_runtime.litertlm_runtime) calls these static methods through Chaquopy.
 * The engine library (com.google.ai.edge.litertlm:litertlm-android, Apache-2.0) is reached by REFLECTION, on purpose:
 *
 *   - an APK built WITHOUT the engine still compiles and runs (isPresent() simply says false, nothing else changes);
 *   - an engine whose API differs from what this file expects cannot break the build - it is reported at run time as
 *     "api_mismatch" together with the name of the missing piece, and the app stays alive.
 *
 * No method here throws: every failure (including OutOfMemoryError, UnsatisfiedLinkError, NoClassDefFoundError) comes back as
 * the string "ERR\n<code>\n<short detail>"; success is "OK\n<text>". The strings carry no user text except the model's own answer.
 *
 * The engine is used the way its Kotlin API documents (see Conversation / Engine / Config): an Engine is built from an
 * EngineConfig(modelPath, Backend.CPU, null..., maxNumTokens, null...) - its one public constructor with every parameter - initialised
 * once (slow: seconds), and every answer is made in a
 * fresh Conversation (system instruction + the last few turns as initial messages), which is closed afterwards - so the model's
 * context never grows without bound and nothing carries over by accident. CPU only: the GPU back-end is the most likely thing to
 * crash a phone natively, and a native crash cannot be caught from Java.
 *
 * UNVERIFIED ON A DEVICE: this file was only exercised against a hand-written stand-in of the engine's classes (a JVM test)
 * and compiled with javac; whether the real engine accepts this call sequence is known only after a real phone runs it.
 */
public final class LiteRtLmBridge {

    private static final String PKG = "com.google.ai.edge.litertlm.";
    private static final char TURN_SEP = '\u001e';
    private static final char FIELD_SEP = '\u001f';
    private static final int MAX_TEXT = 8000;
    private static final int MAX_DETAIL = 160;
    private static final int MAX_TURNS = 6;
    private static final int TOP_K = 40;
    private static final double TOP_P = 0.95;
    private static final double TEMPERATURE = 0.7;

    private static final Object LOCK = new Object();
    private static Object engine;                       // com.google.ai.edge.litertlm.Engine (guarded by LOCK)
    private static volatile boolean loaded;
    private static volatile Object inFlight;            // the Conversation being answered (for cancel; changed only while holding CANCEL_LOCK)
    private static volatile boolean stopRequested;
    private static final Object CANCEL_LOCK = new Object();   // a cancelProcess() call never overlaps the end (and the closing) of the answer it is meant for
    private static final long CANCEL_REPEAT_MS = 200L;         // while an answer goes on after a stop, the request is sent again this often ...
    private static final long CANCEL_GIVE_UP_MS = 60000L;      // ... for at most this long
    private static Object repeatingFor;                        // the Conversation the repeating thread works for (guarded by CANCEL_LOCK)

    private LiteRtLmBridge() {
    }

    // ------------------------------------------------------------------ is the engine in this APK?

    /** True when the engine's classes are in this APK (they are only there in a build made with the engine). Never throws. */
    public static boolean isPresent() {
        try {
            ClassLoader loader = LiteRtLmBridge.class.getClassLoader();
            Class.forName(PKG + "Engine", false, loader);
            Class.forName(PKG + "EngineConfig", false, loader);
            Class.forName(PKG + "Conversation", false, loader);
            return true;
        } catch (Throwable t) {
            return false;
        }
    }

    public static boolean isLoaded() {
        return loaded;
    }

    /** A short diagnostic line (no private data): whether the engine is present, loaded and which API pieces were found. */
    public static String describe() {
        StringBuilder sb = new StringBuilder();
        sb.append("present=").append(isPresent()).append(";loaded=").append(loaded);
        String[] names = {"Engine", "EngineConfig", "Backend$CPU", "Conversation", "ConversationConfig", "Contents", "Message",
                "SamplerConfig", "ThinkingConfig"};
        for (String name : names) {
            boolean found;
            try {
                Class.forName(PKG + name, false, LiteRtLmBridge.class.getClassLoader());
                found = true;
            } catch (Throwable t) {
                found = false;
            }
            sb.append(';').append(name).append('=').append(found);
        }
        return sb.toString();
    }

    // ------------------------------------------------------------------ is the engine's API the one this file was written for?

    /**
     * Checks WITHOUT any model file that every piece of the engine's API that load() and chat() call exists in this APK (classes,
     * constructors, methods). Fetching a model of gigabytes is only worth starting when this says OK. Returns "OK\nready",
     * "ERR\ndependency_missing\nengine" (no engine in this APK) or "ERR\napi_mismatch\n<the first missing piece>". Never throws.
     */
    public static String probe() {
        try {
            if (!isPresent()) {
                return err("dependency_missing", "engine");
            }
            String missing = firstMissingPiece();
            return missing.length() == 0 ? "OK\nready" : err("api_mismatch", missing);
        } catch (Throwable t) {
            return errFrom(t, "api_mismatch");
        }
    }

    /** The first piece of the engine's API that this file needs and the engine does not have ("" when nothing is missing). */
    private static String firstMissingPiece() {
        String[] needed = {"Engine", "EngineConfig", "Backend", "Backend$CPU", "Conversation", "ConversationConfig", "Contents", "Message"};
        for (String name : needed) {
            if (peek(name) == null) {
                return name;
            }
        }
        Class<?> backend = peek("Backend");
        Class<?> cpu = peek("Backend$CPU");
        Class<?> config = peek("EngineConfig");
        Class<?> engineType = peek("Engine");
        Class<?> conversationConfig = peek("ConversationConfig");
        if (!hasCtor(cpu) && !hasCtor(cpu, Integer.class, Integer.class)) {
            return "Backend.CPU()";
        }
        if (engineConfigConstructor(config, backend) == null) {
            return "EngineConfig(String, Backend)";
        }
        try {
            // The configuration load() builds before it touches any model file is plain data (a back-end and a settings object), so it can be
            // built here as a dry run: an "OK" then means this call really works with this engine, not only that a constructor exists.
            newEngineConfig(config, backend, "/probe/model.litertlm", newBackendCpu(), 2048);
        } catch (Throwable t) {
            return "EngineConfig(String, Backend): " + unwrap(t).getClass().getSimpleName();
        }
        if (!hasCtor(engineType, config)) {
            return "Engine(EngineConfig)";
        }
        if (!hasMethod(engineType, "initialize")) {
            return "Engine.initialize()";
        }
        if (!hasMethod(engineType, "createConversation", conversationConfig)) {
            return "Engine.createConversation(ConversationConfig)";
        }
        if (ctorWithArity(conversationConfig, 11) == null && ctorWithArity(conversationConfig, 4) == null
                && ctorWithArity(conversationConfig, 1) == null) {
            return "ConversationConfig(...)";
        }
        if (!companionHas(peek("Contents"), "of")) {
            return "Contents.of(String)";
        }
        if (!companionHas(peek("Message"), "user", "model")) {
            return "Message.user/model(String)";
        }
        if (!hasSendMessage(peek("Conversation"))) {
            return "Conversation.sendMessage(String)";
        }
        return "";
    }

    /**
     * A compact listing of the public constructors and methods of the engine classes this file uses (class names and signatures only, no
     * private data; at most about 6000 characters). It goes into the self-test report: when the engine's API is not what this file
     * expects, THIS tells the developer what it is instead. Never throws.
     */
    public static String api() {
        StringBuilder sb = new StringBuilder();
        try {
            String[] names = {"Engine", "EngineConfig", "Backend", "Backend$CPU", "Conversation", "ConversationConfig", "Contents", "Message",
                    "SamplerConfig", "ThinkingConfig"};
            for (String name : names) {
                Class<?> type = peek(name);
                sb.append(name).append(':');
                if (type == null) {
                    sb.append(" -\n");
                    continue;
                }
                listMembers(sb, type);
                try {
                    Class<?> companion = type.getField("Companion").getType();
                    sb.append(" Companion{");
                    listMembers(sb, companion);
                    sb.append(" }");
                } catch (Throwable noCompanion) {
                    // most classes have none
                }
                sb.append('\n');
                if (sb.length() > 6000) {
                    break;
                }
            }
        } catch (Throwable t) {
            sb.append("?");
        }
        String out = sb.toString();
        return out.length() > 6000 ? out.substring(0, 6000) : out;
    }

    private static void listMembers(StringBuilder sb, Class<?> type) {
        try {
            for (Constructor<?> c : type.getConstructors()) {
                sb.append(" <init>(").append(simpleNames(c.getParameterTypes())).append(");");
            }
            for (Method m : type.getMethods()) {
                if (m.getDeclaringClass() == Object.class) {
                    continue;
                }
                sb.append(' ').append(m.getName()).append('(').append(simpleNames(m.getParameterTypes())).append(");");
            }
        } catch (Throwable t) {
            sb.append(" ?");
        }
    }

    private static String simpleNames(Class<?>[] types) {
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < types.length; i++) {
            if (i > 0) {
                sb.append(',');
            }
            sb.append(types[i].getSimpleName());
        }
        return sb.toString();
    }

    /** The class (not initialised) or null. */
    private static Class<?> peek(String simpleName) {
        try {
            return Class.forName(PKG + simpleName, false, LiteRtLmBridge.class.getClassLoader());
        } catch (Throwable t) {
            return null;
        }
    }

    private static boolean hasCtor(Class<?> type, Class<?>... parameters) {
        try {
            type.getConstructor(parameters);
            return true;
        } catch (Throwable t) {
            return false;
        }
    }

    private static boolean hasMethod(Class<?> type, String name, Class<?>... parameters) {
        try {
            type.getMethod(name, parameters);
            return true;
        } catch (Throwable t) {
            return false;
        }
    }

    /** Does the Kotlin companion of `type` have a method with each of these names taking one String? */
    private static boolean companionHas(Class<?> type, String... names) {
        try {
            Class<?> companion = type.getField("Companion").getType();
            for (String name : names) {
                companion.getMethod(name, String.class);
            }
            return true;
        } catch (Throwable t) {
            return false;
        }
    }

    /** sendMessage(String) or the long form sendMessage(String, Map, ?, ?, ?, Integer): the two shapes sendMessage() below knows. */
    private static boolean hasSendMessage(Class<?> type) {
        try {
            for (Method m : type.getMethods()) {
                if (!"sendMessage".equals(m.getName())) {
                    continue;
                }
                Class<?>[] p = m.getParameterTypes();
                if ((p.length == 6 && p[0] == String.class && p[1] == Map.class && p[5] == Integer.class)
                        || (p.length == 1 && p[0] == String.class)) {
                    return true;
                }
            }
        } catch (Throwable t) {
            return false;
        }
        return false;
    }

    // ------------------------------------------------------------------ load / unload

    /**
     * Builds and initialises the engine for the model file. Slow (seconds to a minute): call it from a background thread.
     * Returns "OK\nloaded" or "ERR\n<code>\n<detail>". A model that is already loaded is released first.
     */
    public static String load(String modelPath, int maxTokens) {
        synchronized (LOCK) {
            try {
                unloadLocked();
                if (modelPath == null || modelPath.length() == 0 || modelPath.length() > 1024) {
                    return err("bad_arguments", "path");
                }
                File file = new File(modelPath);
                if (!file.isFile() || !file.canRead()) {
                    return err("model_file_unreadable", "");
                }
                int tokens = maxTokens < 256 ? 256 : (maxTokens > 32768 ? 32768 : maxTokens);
                Class<?> backendBase = cls("Backend");
                Object backend = newBackendCpu();
                Class<?> configClass = cls("EngineConfig");
                Object config = newEngineConfig(configClass, backendBase, modelPath, backend, tokens);
                Class<?> engineClass = cls("Engine");
                Object created = engineClass.getConstructor(configClass).newInstance(config);
                try {
                    engineClass.getMethod("initialize").invoke(created);
                } catch (Throwable t) {
                    closeQuietly(created);
                    throw t;
                }
                engine = created;
                loaded = true;
                return "OK\nloaded";
            } catch (Throwable t) {
                engine = null;
                loaded = false;
                return errFrom(t, "engine_load_failed");
            }
        }
    }

    /** Releases the engine (and with it the model's memory). Waits for an answer in progress; call cancel() first to hurry it. */
    public static String unload() {
        synchronized (LOCK) {
            try {
                unloadLocked();
                return "OK\nunloaded";
            } catch (Throwable t) {
                return errFrom(t, "unload_failed");
            }
        }
    }

    private static void unloadLocked() {
        Object old = engine;
        engine = null;
        loaded = false;
        if (old != null) {
            closeQuietly(old);
        }
    }

    // ------------------------------------------------------------------ one answer

    /**
     * One answer. `system` is the instruction (may be empty); `history` holds earlier turns as
     * "user\u001Fassistant\u001Euser\u001Fassistant..." (at most the last few are used); `user` is the new message.
     * Returns "OK\n<answer>" or "ERR\n<code>\n<detail>".
     */
    public static String chat(String system, String history, String user, int maxOutputTokens) {
        synchronized (LOCK) {
            if (engine == null) {
                return err("not_loaded", "");
            }
            Object conversation = null;
            try {
                stopRequested = false;
                String question = user == null ? "" : user;
                if (question.trim().length() == 0 || question.length() > MAX_TEXT) {
                    return err("bad_arguments", "user");
                }
                int limit = maxOutputTokens < 1 ? 128 : (maxOutputTokens > 2048 ? 2048 : maxOutputTokens);
                conversation = newConversation(system == null ? "" : system, parseHistory(history), limit);
                synchronized (CANCEL_LOCK) {
                    inFlight = conversation;
                }
                if (stopRequested) {
                    return err("cancelled", "");                    // a stop that came while the conversation was being made: nothing is generated
                }
                Object message = sendMessage(conversation, question, limit);
                if (stopRequested) {
                    return err("cancelled", "");
                }
                String text = message == null ? "" : String.valueOf(message);
                return "OK\n" + text;
            } catch (Throwable t) {
                if (stopRequested) {
                    return err("cancelled", "");
                }
                return errFrom(t, "generate_failed");
            } finally {
                synchronized (CANCEL_LOCK) {
                    inFlight = null;                                // no cancelProcess() is running now, and none can start after this
                }
                closeQuietly(conversation);
            }
        }
    }

    /**
     * Asks the answer in progress (if any) to stop. Safe from any thread; never throws and never waits for the answer. The request is sent at
     * once and then sent again every 200 ms for as long as the SAME answer goes on (at most a minute): one request that arrives a moment before
     * the engine has really started to generate can be lost, and the user's «ایست» must not depend on that moment. The conversation is closed
     * only after the last request has returned (see chat()), never while one is being made.
     */
    public static void cancel() {
        stopRequested = true;
        Object conversation;
        synchronized (CANCEL_LOCK) {
            conversation = inFlight;
            if (conversation == null) {
                return;
            }
            requestStop(conversation);
        }
        repeatStopWhileAnswering(conversation);
    }

    /** One request to the engine; the caller holds CANCEL_LOCK. */
    private static void requestStop(Object conversation) {
        try {
            conversation.getClass().getMethod("cancelProcess").invoke(conversation);
        } catch (Throwable ignored) {
            // the answer then simply ends at its own deadline
        }
    }

    /** One small background thread per answer sends the stop request again until that answer has ended (or a minute has passed). */
    private static void repeatStopWhileAnswering(final Object conversation) {
        synchronized (CANCEL_LOCK) {
            if (repeatingFor == conversation) {
                return;                                             // already repeating for this answer
            }
            repeatingFor = conversation;
        }
        try {
            Thread repeater = new Thread(new Runnable() {
                @Override
                public void run() {
                    long until = System.currentTimeMillis() + CANCEL_GIVE_UP_MS;
                    try {
                        while (System.currentTimeMillis() < until) {
                            Thread.sleep(CANCEL_REPEAT_MS);
                            synchronized (CANCEL_LOCK) {
                                if (inFlight != conversation) {
                                    return;                         // that answer has ended
                                }
                                requestStop(conversation);
                            }
                        }
                    } catch (InterruptedException e) {
                        Thread.currentThread().interrupt();
                    } finally {
                        synchronized (CANCEL_LOCK) {
                            if (repeatingFor == conversation) {
                                repeatingFor = null;
                            }
                        }
                    }
                }
            }, "litertlm-cancel");
            repeater.setDaemon(true);
            repeater.start();
        } catch (Throwable t) {
            synchronized (CANCEL_LOCK) {
                if (repeatingFor == conversation) {
                    repeatingFor = null;
                }
            }
        }
    }

    // ------------------------------------------------------------------ reflection helpers (the engine's Kotlin API)

    private static Class<?> cls(String simpleName) throws ClassNotFoundException {
        return Class.forName(PKG + simpleName, true, LiteRtLmBridge.class.getClassLoader());
    }

    /** Backend.CPU(): Kotlin generates a public no-argument constructor when every parameter has a default value. */
    private static Object newBackendCpu() throws Exception {
        Class<?> cpu = cls("Backend$CPU");
        try {
            return cpu.getConstructor().newInstance();
        } catch (NoSuchMethodException first) {
            return cpu.getConstructor(Integer.class, Integer.class).newInstance(null, null);
        }
    }

    /**
     * The constructor of EngineConfig this file calls: the WIDEST public one that starts (String, Backend) and has only object types after
     * that. Kotlin's `data class EngineConfig(modelPath, backend, visionBackend, audioBackend, maxNumTokens, maxNumImages, cacheDir)` has no
     * @JvmOverloads, so Java sees ONE public constructor with every parameter (all but the first two are nullable: null means "the engine's
     * own default"); a version of the class with fewer parameters, or with the shorter forms as well, is used the same way. Kotlin's synthetic
     * "default values" constructor (an extra int and a marker at the end) is never taken: it has a primitive parameter.
     */
    private static Constructor<?> engineConfigConstructor(Class<?> configClass, Class<?> backendBase) {
        Constructor<?> widest = null;
        for (Constructor<?> c : configClass.getConstructors()) {
            Class<?>[] p = c.getParameterTypes();
            if (p.length < 2 || p[0] != String.class || p[1] != backendBase) {
                continue;
            }
            boolean objectsOnly = true;
            for (int i = 2; i < p.length; i++) {
                if (p[i].isPrimitive()) {
                    objectsOnly = false;
                }
            }
            if (objectsOnly && (widest == null || p.length > widest.getParameterTypes().length)) {
                widest = c;
            }
        }
        return widest;
    }

    /** EngineConfig(path, backend, null, null, <token limit>, null, ...): the first Integer after the back-ends is maxNumTokens. */
    private static Object newEngineConfig(Class<?> configClass, Class<?> backendBase, String path, Object backend, int tokens)
            throws Exception {
        Constructor<?> c = engineConfigConstructor(configClass, backendBase);
        if (c == null) {
            throw new NoSuchMethodException("EngineConfig(String, Backend...)");
        }
        Class<?>[] p = c.getParameterTypes();
        Object[] args = new Object[p.length];
        args[0] = path;
        args[1] = backend;
        boolean limitSet = false;
        for (int i = 2; i < p.length; i++) {
            if (!limitSet && p[i] == Integer.class) {
                args[i] = Integer.valueOf(tokens);
                limitSet = true;
            }
        }
        return c.newInstance(args);
    }

    private static Constructor<?> ctorWithArity(Class<?> type, int arity) {
        for (Constructor<?> c : type.getConstructors()) {
            if (c.getParameterTypes().length == arity) {
                return c;
            }
        }
        return null;
    }

    private static Object companion(Class<?> type) throws Exception {
        return type.getField("Companion").get(null);
    }

    /** Companion.<name>(String): the Kotlin factories (Contents.of, Message.user, Message.model) are not @JvmStatic. */
    private static Object fromText(Object companion, String name, String text) throws Exception {
        Method m = companion.getClass().getMethod(name, String.class);
        return m.invoke(companion, text);
    }

    private static List<String[]> parseHistory(String history) {
        List<String[]> turns = new ArrayList<String[]>();
        if (history == null || history.length() == 0) {
            return turns;
        }
        for (String record : history.split(String.valueOf(TURN_SEP))) {
            int at = record.indexOf(FIELD_SEP);
            if (at <= 0 || at >= record.length() - 1) {
                continue;
            }
            String u = record.substring(0, at);
            String a = record.substring(at + 1);
            if (u.length() > MAX_TEXT || a.length() > MAX_TEXT) {
                continue;
            }
            turns.add(new String[] {u, a});
        }
        int from = turns.size() > MAX_TURNS ? turns.size() - MAX_TURNS : 0;
        return new ArrayList<String[]>(turns.subList(from, turns.size()));
    }

    /** Engine.createConversation(ConversationConfig(system, initialMessages, tools, sampler[, ... thinking off])). Falls back to simpler configs. */
    private static Object newConversation(String system, List<String[]> turns, int maxOutput) throws Throwable {
        Class<?> configClass = cls("ConversationConfig");
        Class<?> engineClass = cls("Engine");
        Method create = engineClass.getMethod("createConversation", configClass);
        Object contentsCompanion = companion(cls("Contents"));
        Object messageCompanion = companion(cls("Message"));
        Object systemContents = system.length() == 0 ? null : fromText(contentsCompanion, "of", system);
        List<Object> initial = new ArrayList<Object>();
        for (String[] turn : turns) {
            initial.add(fromText(messageCompanion, "user", turn[0]));
            initial.add(fromText(messageCompanion, "model", turn[1]));
        }
        Object sampler = newSampler();
        List<Object> noTools = Collections.emptyList();
        Map<String, Object> noContext = Collections.emptyMap();

        Throwable last = null;
        Constructor<?> rich = ctorWithArity(configClass, 11);
        Object thinkingOff = rich == null ? null : newThinkingOff();
        if (rich != null && thinkingOff != null) {
            try {
                Object config = rich.newInstance(systemContents, initial, noTools, sampler, Boolean.TRUE, null, noContext, null,
                        Boolean.FALSE, Integer.valueOf(maxOutput), thinkingOff);
                return create.invoke(engine, config);
            } catch (Throwable t) {
                last = unwrap(t);
                if (last instanceof OutOfMemoryError) {
                    throw last;
                }
            }
        }
        Constructor<?> basic = ctorWithArity(configClass, 4);
        if (basic != null) {
            try {
                Object config = basic.newInstance(systemContents, initial, noTools, sampler);
                return create.invoke(engine, config);
            } catch (Throwable t) {
                last = unwrap(t);
                if (last instanceof OutOfMemoryError) {
                    throw last;
                }
            }
        }
        Constructor<?> bare = ctorWithArity(configClass, 1);
        if (bare != null) {
            Object config = bare.newInstance(systemContents);
            return create.invoke(engine, config);
        }
        if (last != null) {
            throw last;
        }
        throw new NoSuchMethodException("ConversationConfig(...)");
    }

    private static Object newSampler() {
        try {
            return cls("SamplerConfig").getConstructor(int.class, double.class, double.class, int.class)
                    .newInstance(Integer.valueOf(TOP_K), Double.valueOf(TOP_P), Double.valueOf(TEMPERATURE), Integer.valueOf(0));
        } catch (Throwable t) {
            return null;                                        // the engine's own sampler defaults are then used
        }
    }

    private static Object newThinkingOff() {
        try {
            Class<?> thinking = cls("ThinkingConfig");
            try {
                return thinking.getConstructor(boolean.class, int.class).newInstance(Boolean.FALSE, Integer.valueOf(-1));
            } catch (NoSuchMethodException e) {
                return thinking.getConstructor(boolean.class).newInstance(Boolean.FALSE);
            }
        } catch (Throwable t) {
            return null;
        }
    }

    /** Conversation.sendMessage(text, extraContext, ..., maxOutputToken) when it exists, else sendMessage(text). */
    private static Object sendMessage(Object conversation, String text, int maxOutput) throws Throwable {
        Method six = null;
        Method one = null;
        for (Method m : conversation.getClass().getMethods()) {
            if (!"sendMessage".equals(m.getName())) {
                continue;
            }
            Class<?>[] p = m.getParameterTypes();
            if (p.length == 6 && p[0] == String.class && p[1] == Map.class && p[5] == Integer.class) {
                six = m;
            } else if (p.length == 1 && p[0] == String.class) {
                one = m;
            }
        }
        try {
            if (six != null) {
                Map<String, Object> noContext = Collections.emptyMap();
                return six.invoke(conversation, text, noContext, null, null, null, Integer.valueOf(maxOutput));
            }
            if (one != null) {
                return one.invoke(conversation, text);
            }
        } catch (InvocationTargetException e) {
            throw e.getCause() != null ? e.getCause() : e;
        }
        throw new NoSuchMethodException("Conversation.sendMessage(String)");
    }

    private static void closeQuietly(Object closeable) {
        if (closeable == null) {
            return;
        }
        try {
            closeable.getClass().getMethod("close").invoke(closeable);
        } catch (Throwable ignored) {
            // already closed, or never fully built
        }
    }

    // ------------------------------------------------------------------ results

    private static Throwable unwrap(Throwable t) {
        Throwable cur = t;
        while ((cur instanceof InvocationTargetException) && cur.getCause() != null) {
            cur = cur.getCause();
        }
        return cur;
    }

    private static String clip(String text) {
        if (text == null) {
            return "";
        }
        String flat = text.replace('\n', ' ').replace('\r', ' ').replace('\u001e', ' ').replace('\u001f', ' ').trim();
        return flat.length() > MAX_DETAIL ? flat.substring(0, MAX_DETAIL) : flat;
    }

    private static String err(String code, String detail) {
        return "ERR\n" + code + "\n" + clip(detail);
    }

    private static String errFrom(Throwable raw, String defaultCode) {
        Throwable t = unwrap(raw);
        String code = defaultCode;
        String name = t.getClass().getName();
        if (t instanceof OutOfMemoryError) {
            code = "out_of_memory";
        } else if (t instanceof UnsatisfiedLinkError) {
            code = "native_missing";
        } else if (t instanceof ClassNotFoundException || t instanceof NoClassDefFoundError) {
            code = "dependency_missing";
        } else if (t instanceof NoSuchMethodException || t instanceof NoSuchFieldException || t instanceof NoSuchMethodError
                || t instanceof NoSuchFieldError || t instanceof IllegalAccessException || t instanceof IllegalAccessError
                || t instanceof ClassCastException) {
            code = "api_mismatch";
        }
        return err(code, name + ": " + clip(t.getMessage()));
    }
}
