package com.google.ai.edge.litertlm;

/** TEST STAND-IN for an engine whose API DRIFTED: EngineConfig no longer has the constructor shapes the bridge looks for. */
public final class EngineConfig {
    public final String modelPath;
    public final Backend backend = new Backend.CPU();
    public final Integer maxNumTokens = null;

    public EngineConfig(String modelPath, int somethingNew, long somethingElse) {
        this.modelPath = modelPath;
    }
}
