package com.google.ai.edge.litertlm;

/** TEST STAND-IN for the engine: records what it was built with; failures can be injected through StubControl. */
public final class Engine implements AutoCloseable {
    private final EngineConfig config;
    private boolean initialized;

    public Engine(EngineConfig engineConfig) {
        this.config = engineConfig;
        StubControl.lastModelPath = engineConfig.modelPath;
        StubControl.LOG.add("engine:path=" + engineConfig.modelPath + "|backend=" + engineConfig.backend.name
                + "|maxNumTokens=" + engineConfig.maxNumTokens);
    }

    public boolean isInitialized() {
        return initialized;
    }

    public void initialize() {
        if (initialized) {
            throw new IllegalStateException("Engine is already initialized.");
        }
        Throwable failure = StubControl.failInit;
        if (failure != null) {
            if (failure instanceof Error) {
                throw (Error) failure;
            }
            throw (RuntimeException) failure;
        }
        initialized = true;
        StubControl.LOG.add("initialize");
    }

    public Conversation createConversation(ConversationConfig conversationConfig) {
        if (!initialized) {
            throw new IllegalStateException("Engine is not initialized.");
        }
        Runnable hook = StubControl.duringCreate;
        if (hook != null) {
            hook.run();
        }
        if (StubControl.failCreateWithThinking && conversationConfig.thinkingConfig != null) {
            throw new IllegalArgumentException("stand-in: thinking is not supported by this model");
        }
        if (StubControl.failBasicConfig && conversationConfig.samplerConfig != null && conversationConfig.maxOutputToken == null) {
            throw new IllegalStateException("stand-in: a conversation with a sampler but no output limit is refused");
        }
        String system = conversationConfig.systemInstruction == null ? "" : conversationConfig.systemInstruction.toString();
        StringBuilder messages = new StringBuilder();
        if (conversationConfig.initialMessages != null) {
            for (Message m : conversationConfig.initialMessages) {
                messages.append(m.role).append(':').append(m).append(';');
            }
        }
        StubControl.LOG.add("conversation:system=" + system + "|initial=" + messages + "|maxOut=" + conversationConfig.maxOutputToken
                + "|thinkingOff=" + (conversationConfig.thinkingConfig != null && !conversationConfig.thinkingConfig.enableThinking)
                + "|sampler=" + (conversationConfig.samplerConfig == null ? "none" : conversationConfig.samplerConfig.topK + "/"
                + conversationConfig.samplerConfig.temperature));
        return new Conversation(conversationConfig);
    }

    @Override
    public void close() {
        if (!initialized) {
            throw new IllegalStateException("Engine is not initialized.");
        }
        initialized = false;
        StubControl.closedEngines++;
        StubControl.LOG.add("engine-closed");
    }
}
