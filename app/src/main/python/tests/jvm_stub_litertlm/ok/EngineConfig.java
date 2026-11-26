package com.google.ai.edge.litertlm;

/**
 * TEST STAND-IN shaped like the compiled Kotlin `data class EngineConfig(modelPath, backend = Backend.CPU(), visionBackend = null,
 * audioBackend = null, maxNumTokens = null, maxNumImages = null, cacheDir = null)` of the engine's Config.kt: NO @JvmOverloads, so Java sees ONE public
 * constructor with every parameter, plus Kotlin's synthetic "default values" constructor (an int mask and a marker at the end).
 */
public final class EngineConfig {
    public final String modelPath;
    public final Backend backend;
    public final Backend visionBackend;
    public final Backend audioBackend;
    public final Integer maxNumTokens;
    public final Integer maxNumImages;
    public final String cacheDir;

    public EngineConfig(String modelPath, Backend backend, Backend visionBackend, Backend audioBackend, Integer maxNumTokens, Integer maxNumImages,
                        String cacheDir) {
        if (modelPath == null || backend == null) {                  // what Kotlin's own null checks of the two non-null parameters do
            throw new IllegalArgumentException("Parameter specified as non-null is null");
        }
        if (maxNumTokens != null && maxNumTokens <= 0) {
            throw new IllegalArgumentException("maxNumToken must be positive or null (use the default from model or engine).");
        }
        if (maxNumImages != null && maxNumImages <= 0) {
            throw new IllegalArgumentException("maxNumImages must be positive or null (use the default from model or engine).");
        }
        StubControl.LOG.add("config:path=" + modelPath + "|maxNumTokens=" + maxNumTokens + "|maxNumImages=" + maxNumImages + "|cacheDir=" + cacheDir
                + "|vision=" + visionBackend + "|audio=" + audioBackend);
        this.modelPath = modelPath;
        this.backend = backend;
        this.visionBackend = visionBackend;
        this.audioBackend = audioBackend;
        this.maxNumTokens = maxNumTokens;
        this.maxNumImages = maxNumImages;
        this.cacheDir = cacheDir;
    }

    /** The synthetic constructor Kotlin adds for default values: public, with a primitive mask and a marker object at the end. Never to be called. */
    public EngineConfig(String modelPath, Backend backend, Backend visionBackend, Backend audioBackend, Integer maxNumTokens, Integer maxNumImages,
                        String cacheDir, int defaultsMask, Object marker) {
        throw new UnsupportedOperationException("stand-in: the synthetic default-values constructor must never be called");
    }
}
