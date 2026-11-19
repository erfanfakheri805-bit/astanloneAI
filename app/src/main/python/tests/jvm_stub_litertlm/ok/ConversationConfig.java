package com.google.ai.edge.litertlm;

import java.util.List;
import java.util.Map;

/** TEST STAND-IN: `data class ConversationConfig @JvmOverloads constructor(...)` (only the overloads the bridge could use are present). */
public final class ConversationConfig {
    public final Contents systemInstruction;
    public final List<Message> initialMessages;
    public final SamplerConfig samplerConfig;
    public final Integer maxOutputToken;
    public final ThinkingConfig thinkingConfig;

    public ConversationConfig() {
        this(null);
    }

    public ConversationConfig(Contents systemInstruction) {
        this(systemInstruction, java.util.Collections.<Message>emptyList());
    }

    @SuppressWarnings("unchecked")
    public ConversationConfig(Contents systemInstruction, List<Message> initialMessages) {
        this(systemInstruction, initialMessages, java.util.Collections.<ToolProvider>emptyList());
    }

    public ConversationConfig(Contents systemInstruction, List<Message> initialMessages, List<ToolProvider> tools) {
        this(systemInstruction, initialMessages, tools, null);
    }

    public ConversationConfig(Contents systemInstruction, List<Message> initialMessages, List<ToolProvider> tools, SamplerConfig samplerConfig) {
        this.systemInstruction = systemInstruction;
        this.initialMessages = initialMessages;
        this.samplerConfig = samplerConfig;
        this.maxOutputToken = null;
        this.thinkingConfig = null;
    }

    public ConversationConfig(Contents systemInstruction, List<Message> initialMessages, List<ToolProvider> tools, SamplerConfig samplerConfig,
                              boolean automaticToolCalling, List<?> channels, Map<String, Object> extraContext, LoraConfig loraConfig,
                              boolean prefillPrefaceOnInit, Integer maxOutputToken, ThinkingConfig thinkingConfig) {
        if (StubControl.failRichConfig) {
            throw new IllegalArgumentException("stand-in: the rich configuration is refused");
        }
        if (maxOutputToken != null && maxOutputToken <= 0) {
            throw new IllegalArgumentException("maxOutputToken must be positive or null");
        }
        this.systemInstruction = systemInstruction;
        this.initialMessages = initialMessages;
        this.samplerConfig = samplerConfig;
        this.maxOutputToken = maxOutputToken;
        this.thinkingConfig = thinkingConfig;
    }
}
