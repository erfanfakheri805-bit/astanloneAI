package com.google.ai.edge.litertlm;

/** TEST STAND-IN: `data class ThinkingConfig @JvmOverloads constructor(enableThinking = true, thinkingTokenBudget = -1)`. */
public final class ThinkingConfig {
    public final boolean enableThinking;
    public final int thinkingTokenBudget;

    public ThinkingConfig() {
        this(true, -1);
    }

    public ThinkingConfig(boolean enableThinking) {
        this(enableThinking, -1);
    }

    public ThinkingConfig(boolean enableThinking, int thinkingTokenBudget) {
        this.enableThinking = enableThinking;
        this.thinkingTokenBudget = thinkingTokenBudget;
    }
}
