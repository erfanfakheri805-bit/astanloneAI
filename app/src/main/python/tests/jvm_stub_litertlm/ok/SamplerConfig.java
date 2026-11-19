package com.google.ai.edge.litertlm;

/** TEST STAND-IN: `data class SamplerConfig(topK, topP, temperature, seed = 0)` - no @JvmOverloads, so only the full constructor. */
public final class SamplerConfig {
    public final int topK;
    public final double topP;
    public final double temperature;
    public final int seed;

    public SamplerConfig(int topK, double topP, double temperature, int seed) {
        if (topK <= 0 || topP < 0 || topP > 1 || temperature < 0) {
            throw new IllegalArgumentException("bad sampler");
        }
        this.topK = topK;
        this.topP = topP;
        this.temperature = temperature;
        this.seed = seed;
    }
}
