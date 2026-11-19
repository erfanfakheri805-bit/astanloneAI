package com.google.ai.edge.litertlm;

/** TEST STAND-IN: `data class EngineConfig @JvmOverloads constructor(...)` - @JvmOverloads yields every shorter constructor. */
public final class EngineConfig {
    public final String modelPath;
    public final Backend backend;
    public final Integer maxNumTokens;

    public EngineConfig(String modelPath) {
        this(modelPath, new Backend.CPU());
    }

    public EngineConfig(String modelPath, Backend backend) {
        this(modelPath, backend, null);
    }

    public EngineConfig(String modelPath, Backend backend, Backend visionBackend) {
        this(modelPath, backend, visionBackend, null);
    }

    public EngineConfig(String modelPath, Backend backend, Backend visionBackend, Backend audioBackend) {
        this(modelPath, backend, visionBackend, audioBackend, null);
    }

    public EngineConfig(String modelPath, Backend backend, Backend visionBackend, Backend audioBackend, Integer maxNumTokens) {
        if (maxNumTokens != null && maxNumTokens <= 0) {
            throw new IllegalArgumentException("maxNumToken must be positive or null");
        }
        this.modelPath = modelPath;
        this.backend = backend;
        this.maxNumTokens = maxNumTokens;
    }
}
