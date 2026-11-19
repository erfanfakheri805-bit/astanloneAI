package com.google.ai.edge.litertlm;

import java.util.Map;

/** TEST STAND-IN for the engine's Conversation (constructed only by Engine.createConversation). */
public final class Conversation implements AutoCloseable {
    private final ConversationConfig config;
    private boolean closed;

    Conversation(ConversationConfig config) {
        this.config = config;
    }

    public Message sendMessage(String text) {
        return sendMessage(text, java.util.Collections.<String, Object>emptyMap(), null, null, null, null);
    }

    public Message sendMessage(String text, Map<String, Object> extraContext, RepetitionPenaltyConfig a, NoRepeatNgramConfig b,
                               SuppressTokensConfig c, Integer maxOutputToken) {
        return sendMessage(text, extraContext, a, b, c, maxOutputToken, null, null, null);
    }

    public Message sendMessage(String text, Map<String, Object> extraContext, RepetitionPenaltyConfig a, NoRepeatNgramConfig b,
                               SuppressTokensConfig c, Integer maxOutputToken, ThinkingConfig thinking, ResponseFormat format, ToolChoice choice) {
        if (closed) {
            throw new IllegalStateException("conversation is not alive");
        }
        StubControl.LOG.add("send:" + text + "|max=" + maxOutputToken);
        long until = System.currentTimeMillis() + StubControl.answerDelayMs;
        while (System.currentTimeMillis() < until) {
            if (StubControl.cancelRequested) {
                throw new IllegalStateException("stand-in: cancelled by cancelProcess");
            }
            try {
                Thread.sleep(5);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                break;
            }
        }
        int earlier = config.initialMessages == null ? 0 : config.initialMessages.size();
        return Message.Companion.model("پاسخ|" + text + "|earlier=" + earlier);
    }

    public Message sendMessage(Message message) {
        return sendMessage(message.toString());
    }

    public Message sendMessage(Contents contents) {
        return sendMessage(contents.toString());
    }

    public void cancelProcess() {
        StubControl.LOG.add("cancelProcess");
        StubControl.cancelRequested = true;
    }

    @Override
    public void close() {
        closed = true;
        StubControl.closedConversations++;
    }
}
